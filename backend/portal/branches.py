"""A logical turn is one slot (conversation, predecessor). Each slot remembers its selected child."""

from collections import defaultdict

from rest_framework.exceptions import NotFound, ValidationError


class RequestConflict(ValidationError):
    status_code = 409


UNSPECIFIED = object()


class BranchState:
    def __init__(self, chat):
        self.previous = {}
        self.groups = defaultdict(list)
        selected = {}
        rows = (
            chat.messages.filter(role="user")
            .order_by("-pk")
            .values_list("pk", "previous_turn_id", "selected_version")
        )
        for pk, parent, active in rows:
            self.previous[pk] = parent
            self.groups[parent].append(pk)
            if active:
                selected[parent] = pk
        self.path = []
        current = selected.get(None)
        while current is not None:
            self.path.append(current)
            current = selected.get(current)

    @property
    def leaf(self):
        return self.path[-1] if self.path else None

    def check_leaf(self, expected):
        if expected is not UNSPECIFIED and expected != self.leaf:
            raise RequestConflict(
                "شاخهٔ گفتگو تغییر کرده است. نسخهٔ جاری را دوباره بررسی کنید."
            )

    def versions(self, pk):
        if pk not in self.previous:
            raise NotFound("نسخهٔ پیام در این گفتگو پیدا نشد.")
        return self.groups[self.previous[pk]]

    def prefix(self, pk):
        self.versions(pk)
        if pk not in self.path:
            raise RequestConflict(
                "برای ویرایش یا جابه‌جایی، نسخهٔ فعال این نوبت را انتخاب کنید."
            )
        return self.path[: self.path.index(pk)]
