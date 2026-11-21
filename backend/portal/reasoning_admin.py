"""Human-editable partial overrides. Saving a form only pins the selected facts."""

from django import forms

from .capabilities import resolve
from .models import LanguageModel
from .reasoning_contracts import WIRE

TITLES = {
    "reasoning": "پشتیبانی از استدلال",
    "wire": "قرارداد ارسال",
    "reasoning_mandatory": "استدلال اجباری",
    "reasoning_toggle": "امکان روشن و خاموش کردن",
    "efforts": "سطوح مجاز",
    "default_effort": "سطح پیش‌فرض",
    "effort_required": "انتخاب سطح الزامی",
    "budget_required": "انتخاب بودجه الزامی",
    "toggle_required": "انتخاب روشن یا خاموش الزامی",
    "default_enabled": "پیش‌فرض روشن",
    "budget_tokens": "بازهٔ بودجه",
    "budget_presets": "بودجه‌های آماده",
    "default_budget": "بودجهٔ پیش‌فرض",
}


def boolean_override(key):
    return forms.TypedChoiceField(
        label=TITLES[key],
        choices=[("", "نامعلوم"), ("yes", "بله"), ("no", "خیر")],
        coerce=lambda v: v == "yes",
        empty_value=None,
        required=False,
    )


class CatalogModelForm(forms.ModelForm):
    pin = forms.MultipleChoiceField(
        label="تنظیمات دستی",
        choices=TITLES.items(),
        required=False,
        help_text="فقط موارد انتخاب‌شده ذخیره می‌شوند. برای بازگشت به کشف خودکار، انتخاب مورد را بردارید.",
    )
    wire = forms.ChoiceField(
        label=TITLES["wire"],
        choices=[("", "نامعلوم"), *((v, v) for v in WIRE)],
        required=False,
    )
    efforts = forms.MultipleChoiceField(label=TITLES["efforts"], required=False)
    custom_efforts = forms.CharField(
        label="سطوح جدید",
        required=False,
        help_text="مقدارهای دقیق API را با ویرگول جدا کنید.",
    )
    default_effort = forms.CharField(
        label=TITLES["default_effort"], required=False, max_length=128
    )
    budget_min = forms.IntegerField(label="حداقل بودجه", min_value=1, required=False)
    budget_max = forms.IntegerField(label="حداکثر بودجه", min_value=1, required=False)
    budget_presets = forms.CharField(
        label=TITLES["budget_presets"],
        required=False,
        help_text="تعداد توکن‌ها با ویرگول جدا شود.",
    )
    default_budget = forms.IntegerField(
        label=TITLES["default_budget"], min_value=1, required=False
    )
    reasoning = boolean_override("reasoning")
    reasoning_mandatory = boolean_override("reasoning_mandatory")
    reasoning_toggle = boolean_override("reasoning_toggle")
    effort_required = boolean_override("effort_required")
    toggle_required = boolean_override("toggle_required")
    budget_required = boolean_override("budget_required")
    default_enabled = boolean_override("default_enabled")

    class Meta:
        model = LanguageModel
        exclude = ["reasoning_overrides"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        facts, _ = resolve(self.instance)
        values = {**facts, **self.instance.reasoning_overrides}
        self.initial["pin"] = list(self.instance.reasoning_overrides)
        known = values.get("efforts", [])
        self.fields["efforts"].choices = [(v, v) for v in known]
        for key in TITLES:
            v = values.get(key)
            if key == "budget_tokens":
                self.initial.update(
                    budget_min=(v or {}).get("min"), budget_max=(v or {}).get("max")
                )
            elif key == "budget_presets":
                self.initial[key] = ", ".join(map(str, v or []))
            else:
                self.initial[key] = ("yes" if v else "no") if type(v) is bool else v

    def clean(self):
        data = super().clean()
        for key, fallback in (
            ("thinking_levels", []),
            ("thinking_budgets", {}),
            ("capability_overrides", {}),
        ):
            if data.get(key) is None:
                data[key] = fallback
        overrides = {}
        for key in data.get("pin", []):
            value = data.get(key)
            if key == "efforts":
                custom = (data.get("custom_efforts") or "").replace("،", ",").split(",")
                value = list(
                    dict.fromkeys(
                        [*(value or []), *(x.strip() for x in custom if x.strip())]
                    )
                )
            elif key == "budget_tokens":
                value = {"min": data.get("budget_min"), "max": data.get("budget_max")}
            elif key == "budget_presets":
                try:
                    value = [
                        int(v.strip())
                        for v in (value or "").replace("،", ",").split(",")
                    ]
                except ValueError:
                    self.add_error(key, "بودجه‌ها باید عدد صحیح باشند.")
                    continue
            overrides[key] = value
        self.override_changed = overrides != self.instance.reasoning_overrides
        self.instance.reasoning_overrides = overrides
        return data
