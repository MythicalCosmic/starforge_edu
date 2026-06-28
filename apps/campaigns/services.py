"""SMS campaign services (F10-1): build a campaign against a student segment (freezing
the recipient list + phones), then send it once via the Eskiz client."""

from __future__ import annotations

from django.db import transaction
from django.db.models import Count
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.campaigns.models import Campaign, CampaignRecipient, DoNotContact
from apps.students.models import StudentProfile
from core.exceptions import NotFoundException, UnprocessableEntity, ValidationException
from infrastructure.sms.eskiz_client import get_sms_client


def _resolve_phone(student: StudentProfile) -> str:
    """The number a student's message goes to: the primary guardian's (else any
    guardian's), falling back to the student's own. Uses the prefetched guardian list
    so building a campaign stays a fixed number of queries."""
    guardians = list(student.guardians.all())
    guardians.sort(key=lambda g: not g.is_primary)  # primary first
    for g in guardians:
        parent_user = getattr(g.parent, "user", None)
        if parent_user and parent_user.phone:
            return parent_user.phone
    if student.user and student.user.phone:
        return student.user.phone
    return ""


def _segment_queryset(segment: dict, branch):
    qs = StudentProfile.objects.all()
    if branch is not None:
        qs = qs.filter(branch=branch)
    status = segment.get("status")
    if status:
        if status not in StudentProfile.Status.values:
            raise ValidationException(
                _("Unknown student status in the segment."), code="segment_status_invalid"
            )
        qs = qs.filter(status=status)
    cohort = segment.get("cohort")
    if cohort is not None:
        # bool is a subclass of int — reject it so {"cohort": true} can't silently
        # become current_cohort_id=1 and mis-target an audience.
        if not isinstance(cohort, int) or isinstance(cohort, bool):
            raise ValidationException(_("segment.cohort must be a cohort id."), code="segment_cohort_invalid")
        qs = qs.filter(current_cohort_id=cohort)
    return qs


@transaction.atomic
def create_campaign(*, name: str, message: str, segment: dict | None, created_by, branch=None) -> Campaign:
    """Freeze the audience: resolve every student in the segment to a recipient row +
    phone now, so the campaign is an exact, auditable record even if the roster changes
    later. Recipients without any phone are marked SKIPPED up front (never silently
    dropped)."""
    segment = {k: v for k, v in (segment or {}).items() if k in ("status", "cohort") and v not in (None, "")}
    students = list(
        _segment_queryset(segment, branch).select_related("user").prefetch_related("guardians__parent__user")
    )
    campaign = Campaign.objects.create(
        name=name,
        message=message,
        segment=segment,
        branch=branch,
        created_by=created_by,
        total=len(students),
    )
    # Consent: a phone on the do-not-contact list is suppressed up front (a recipient is
    # never even queued for it), so an opted-out family is excluded by construction.
    suppressed = set(DoNotContact.objects.values_list("phone", flat=True))
    rows = []
    skipped = 0
    for student in students:
        phone = _resolve_phone(student)
        opted_out = bool(phone) and phone in suppressed
        skip = not phone or opted_out
        if skip:
            skipped += 1
        rows.append(
            CampaignRecipient(
                campaign=campaign,
                student=student,
                phone=phone,
                status=(CampaignRecipient.Status.SKIPPED if skip else CampaignRecipient.Status.PENDING),
                # distinguish a consent skip from a no-phone skip in the audit trail
                error=("do_not_contact" if opted_out else ""),
            )
        )
    CampaignRecipient.objects.bulk_create(rows)
    if skipped:
        campaign.skipped_count = skipped
        campaign.save(update_fields=["skipped_count", "updated_at"])
    return campaign


def send_campaign(*, campaign_id: int, actor=None) -> Campaign:
    """Send (or resume) a campaign. Three phases on purpose:

    1. CLAIM (a short locked transaction): flip DRAFT -> SENDING so a concurrent or
       retried send serialises on the lock and the loser sees SENDING; a terminal
       SENT/FAILED campaign 422s. A campaign already in SENDING (a previous run died
       mid-send) is RESUMABLE — re-invoking processes only its remaining PENDING rows.
    2. SEND (outside any transaction): the external SMS calls must NOT run inside a DB
       transaction — a rollback can't unsend a message, and a row lock must not be held
       across network I/O. Recipients are deduped by phone (siblings sharing a guardian
       are texted once), and neither a send NOR a save failure aborts the batch.
    3. FINALIZE: recompute counts from the persisted recipient rows, so the totals are
       correct even after a partial/earlier run; leftover PENDING keeps it SENDING.
    """
    R = CampaignRecipient.Status
    with transaction.atomic():
        campaign = Campaign.objects.select_for_update().filter(pk=campaign_id).first()
        if campaign is None:
            raise NotFoundException(_("Campaign not found."), code="campaign_not_found")
        if campaign.status not in (Campaign.Status.DRAFT, Campaign.Status.SENDING):
            raise UnprocessableEntity(_("This campaign has already been sent."), code="campaign_already_sent")
        if campaign.status == Campaign.Status.DRAFT:
            campaign.status = Campaign.Status.SENDING
            campaign.sent_by = actor
            campaign.save(update_fields=["status", "sent_by", "updated_at"])

    client = get_sms_client()
    # Phones already delivered (this run or a prior partial run) — never text twice.
    texted = set(campaign.recipients.filter(status=R.SENT).values_list("phone", flat=True))
    # Honour an opt-out recorded AFTER the build: a now-suppressed phone is skipped, not
    # sent (consent wins over a frozen recipient list).
    suppressed = set(DoNotContact.objects.values_list("phone", flat=True))
    for recipient in campaign.recipients.filter(status=R.PENDING):
        if recipient.phone in suppressed:
            recipient.status = R.SKIPPED
            recipient.error = "do_not_contact"
            recipient.save(update_fields=["status", "error", "sent_at"])
            continue
        try:
            if recipient.phone not in texted:
                client.send(phone=recipient.phone, text=campaign.message)
                texted.add(recipient.phone)
            recipient.status = R.SENT
            recipient.sent_at = timezone.now()
            recipient.save(update_fields=["status", "error", "sent_at"])
        except Exception as exc:  # one bad recipient must not abort the batch
            try:
                recipient.status = R.FAILED
                recipient.error = str(exc)[:255]
                recipient.save(update_fields=["status", "error", "sent_at"])
            except Exception:
                pass  # even a save failure can't abort the run — row stays PENDING, retried on resume

    by = {row["status"]: row["n"] for row in campaign.recipients.values("status").annotate(n=Count("id"))}
    campaign.sent_count = by.get(R.SENT, 0)
    campaign.failed_count = by.get(R.FAILED, 0)
    campaign.skipped_count = by.get(R.SKIPPED, 0)
    campaign.sent_at = timezone.now()
    if by.get(R.PENDING, 0):
        campaign.status = Campaign.Status.SENDING  # partial — still resumable
    elif campaign.sent_count == 0 and campaign.failed_count > 0:
        campaign.status = Campaign.Status.FAILED
    else:
        campaign.status = Campaign.Status.SENT
    campaign.save(
        update_fields=["sent_count", "failed_count", "skipped_count", "sent_at", "status", "updated_at"]
    )
    return campaign
