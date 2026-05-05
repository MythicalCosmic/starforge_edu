"""Default DRF pagination classes."""

from rest_framework.pagination import CursorPagination, PageNumberPagination


class DefaultPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 200


class TimelinePagination(CursorPagination):
    """Use for activity feeds / audit logs / append-only timelines."""

    page_size = 50
    ordering = "-created_at"
    cursor_query_param = "cursor"
