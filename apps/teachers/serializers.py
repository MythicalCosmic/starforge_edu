from rest_framework import serializers

from apps.org.models import Branch, Department
from apps.teachers.models import TeacherProfile
from apps.users.serializers import UserBriefSerializer


class TeacherReadSerializer(serializers.ModelSerializer):
    user = UserBriefSerializer(read_only=True)

    class Meta:
        model = TeacherProfile
        fields = (
            "id",
            "user",
            "branch",
            "department",
            "hire_date",
            "subjects",
            "qualifications",
            "salary_type",
            "rate",
            "is_substitute",
            "created_at",
        )
        read_only_fields = ("created_at",)


class TeacherCreateSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")
    email = serializers.EmailField(required=False, allow_blank=True, default="")
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    middle_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    branch = serializers.PrimaryKeyRelatedField(queryset=Branch.objects.all())
    department = serializers.PrimaryKeyRelatedField(
        queryset=Department.objects.all(), required=False, allow_null=True
    )
    hire_date = serializers.DateField(required=False, allow_null=True)
    subjects = serializers.JSONField(required=False)
    qualifications = serializers.CharField(required=False, allow_blank=True, default="")
    salary_type = serializers.ChoiceField(
        choices=TeacherProfile.SalaryType.choices,
        required=False,
        default=TeacherProfile.SalaryType.MONTHLY,
    )
    rate = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True)
    is_substitute = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        if not attrs.get("phone") and not attrs.get("email"):
            raise serializers.ValidationError({"phone": "Provide a phone or an email."})
        return attrs


class TeacherUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = TeacherProfile
        fields = (
            "branch",
            "department",
            "hire_date",
            "subjects",
            "qualifications",
            "salary_type",
            "rate",
            "is_substitute",
        )
