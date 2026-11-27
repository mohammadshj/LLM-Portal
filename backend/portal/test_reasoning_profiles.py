import json
from unittest.mock import patch

import httpx
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.test import APIClient

from .capabilities import (
    reasoning_evidence,
    runtime_model,
)
from .catalog_metadata import provider_facts, registry_facts
from .discovery import sync_models
from .models import Conversation, Message, ModelConnection
from .reasoning_admin import CatalogModelForm
from .test_connections import upstream


class ProfileTests(TestCase):
    def setUp(self):
        self.conn = ModelConnection.objects.create(
            name="catalog", base_url="https://gateway.example/v1", api_key_env=""
        )
        self.user = get_user_model().objects.create_user("profiles")
        self.chat = Conversation.objects.create(user=self.user, title="comparison")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.url = f"/api/conversations/{self.chat.pk}/"

    def sync(self, rows, registry=None):
        with (
            patch("portal.discovery.read_json", return_value={"data": rows}),
            patch("portal.registry.lookup", return_value=(registry or {}, "cached")),
        ):
            return sync_models(self.conn.pk)

    def model(self, ident):
        return self.conn.models.get(model_id=ident)

    def test_metadata_dialects_and_unknown_semantics(self):
        opts = [
            "none",
            "medium",
            {"value": "X.custom", "label": "عمیق", "semantic_level": "maximum"},
        ]
        row = {
            "id": "one",
            "reasoning_options": [{"type": "effort", "values": opts}],
            "reasoning_contract": "native_effort",
        }
        self.sync(
            [
                row,
                {"id": "no-wire", "reasoning_effort": ["none", "medium", "xhigh"]},
                {"id": "no", "capabilities": {"reasoning": False}},
                {"id": "unknown"},
                {
                    "id": "fixed",
                    "reasoning_contract": "always",
                    "capabilities": {"reasoning": True},
                },
            ]
        )
        profile = runtime_model(self.model("one")).reasoning_profile
        self.assertEqual(profile.public()["mode"], "effort")
        options = profile.controls[0]["options"]
        self.assertEqual([o["value"] for o in options], ["none", "medium", "X.custom"])
        self.assertEqual(
            [o["semantic_level"] for o in options], ["unknown", "unknown", "maximum"]
        )
        self.assertEqual(options[2]["label"], "عمیق")
        self.assertEqual(
            profile.payload({"effort": "X.custom"}), {"reasoning_effort": "X.custom"}
        )
        self.assertEqual(profile.payload({}), {})
        for ident, state, mode in [
            ("no-wire", True, "unknown"),
            ("no", False, "none"),
            ("unknown", None, "unknown"),
            ("fixed", True, "fixed"),
        ]:
            with self.subTest(model=ident):
                profile = runtime_model(self.model(ident)).reasoning_profile
                self.assertEqual(
                    (profile.supported, profile.public()["mode"]), (state, mode)
                )
                with self.assertRaises(ValidationError):
                    profile.payload({"toggle": False})

    def test_structured_effort_accepts_opaque_value_outside_old_slug_column(self):
        raw = "vendor:deep/research-version-123456789.abcdef"
        self.sync(
            [
                {
                    "id": "opaque",
                    "reasoning_contract": "native_effort",
                    "reasoning_effort": [raw],
                }
            ]
        )
        model = runtime_model(self.model("opaque"))
        self.assertEqual(
            model.reasoning_profile.payload({"effort": raw}), {"reasoning_effort": raw}
        )
        self.assertEqual(model.thinking_levels, [])

    def test_conflicting_sources_resync_and_endpoint_change(self):
        row = {
            "id": "one",
            "reasoning_contract": "native_effort",
            "reasoning_effort": ["one", "two"],
        }
        self.sync([row], {"one": {"reasoning": False, "efforts": ["registry"]}})
        model = self.model("one")
        model.reasoning_overrides = {"wire": "router_effort", "efforts": ["two"]}
        model.full_clean()
        model.save()
        self.sync([{**row, "reasoning_effort": ["three"]}])
        model.refresh_from_db()
        evidence = reasoning_evidence(model, ["efforts", "wire"])
        self.assertEqual(
            evidence["efforts"],
            dict(
                value=["two"],
                source="manual",
                verification="operator_confirmed",
                overridden=True,
                conflicts={"provider": ["three"]},
            ),
        )
        self.assertEqual(
            runtime_model(model).reasoning_profile.payload({"effort": "two"}),
            {"reasoning": {"effort": "two"}},
        )
        self.conn.base_url = "https://other.example/v1"
        self.conn.save()
        model.refresh_from_db()
        self.assertIsNone(runtime_model(model).reasoning_profile.supported)
        self.assertEqual(reasoning_evidence(model, ["wire"])["wire"]["conflicts"], {})

    def test_combined_and_range_budget_never_exceed_output_cap(self):
        row = {
            "id": "combo",
            "reasoning_contract": "thinking_controls",
            "reasoning_options": [
                {"type": "toggle"},
                {"type": "budget_tokens", "min": 32, "max": 8192},
                {
                    "type": "effort",
                    "values": ["none", "medium", "custom"],
                    "required": True,
                },
            ],
        }
        self.sync([row])
        profile = runtime_model(self.model("combo")).reasoning_profile
        self.assertEqual(profile.public()["mode"], "combined")
        self.assertEqual(
            profile.payload({"toggle": True, "budget": 400, "effort": "custom"}),
            {
                "reasoning_effort": "custom",
                "thinking": {"type": "enabled", "budget_tokens": 400},
            },
        )
        self.assertEqual(
            profile.payload({"toggle": False}), {"thinking": {"type": "disabled"}}
        )
        for bad in [
            {},
            {"toggle": False, "effort": "custom"},
            {"toggle": 0},
            {"effort": "other"},
            {"effort": "medium", "budget": True},
            {"effort": "custom", "budget": 512},
            {"effort": "none", "budget": "64"},
        ]:
            with self.subTest(value=bad), self.assertRaises(ValidationError):
                profile.payload(bad)
        self.sync([{**row, "reasoning_mandatory": True}])
        profile = runtime_model(self.model("combo")).reasoning_profile
        self.assertNotIn("toggle", [c["type"] for c in profile.controls])
        self.assertEqual(
            profile.payload({"effort": "none"})["reasoning_effort"], "none"
        )

    def test_registry_limits_require_wire_and_conflicting_router_inputs_rejected(self):
        facts = registry_facts(
            {
                "reasoning_options": [
                    {"type": "toggle"},
                    {"type": "budget_tokens", "min": 32, "max": 256},
                ]
            }
        )
        self.sync([{"id": "r", "reasoning_effort": ["low"]}], {"r": facts})
        model = self.model("r")
        self.assertEqual(runtime_model(model).reasoning_profile.controls, [])
        model.reasoning_overrides = {"wire": "router_effort"}
        profile = runtime_model(model).reasoning_profile
        self.assertEqual(
            profile.payload({"budget": 40}), {"reasoning": {"max_tokens": 40}}
        )
        self.assertEqual(
            profile.payload({"toggle": False}), {"reasoning": {"enabled": False}}
        )
        with self.assertRaises(ValidationError):
            profile.payload({"budget": 40, "effort": "low"})

    def test_structured_request_and_default_through_mock_http(self):
        rows = [
            {
                "id": "range",
                "reasoning_contract": "budget_tokens",
                "reasoning_options": [{"type": "budget_tokens", "values": [64, 256]}],
            },
            {
                "id": "toggle",
                "reasoning_contract": "toggle",
                "reasoning_options": [{"type": "toggle"}],
            },
            {
                "id": "e",
                "reasoning_contract": "native_effort",
                "reasoning_effort": ["custom"],
            },
        ]
        self.sync(rows)
        self.conn.models.update(
            enabled=True,
            input_price_per_million_rial=0,
            output_price_per_million_rial=0,
        )
        ids = [self.model(r["id"]).pk for r in rows]
        settings = {
            str(k): v
            for k, v in zip(ids, [{"budget": 64}, {"toggle": False}, {}], strict=True)
        }
        data = dict(content="question", model_ids=ids, reasoning=settings)
        seen = {}

        def handle(req):
            wire = json.loads(req.content)
            seen[wire["model"]] = wire
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "answer"}}]}
            )

        with upstream(handle):
            for invalid in [
                {str(ids[0]): {"budget": 33}},
                {str(ids[2]): {"wire": "router_effort"}},
                {"other": {}},
                {str(ids[1]): {"toggle": 1}},
            ]:
                with self.subTest(invalid=invalid):
                    self.assertEqual(
                        self.client.post(
                            self.url, {**data, "reasoning": invalid}, format="json"
                        ).status_code,
                        400,
                    )
            self.assertEqual(
                self.client.post(
                    self.url,
                    {**data, "thinking": {str(ids[2]): "custom"}},
                    format="json",
                ).status_code,
                400,
            )
            self.assertEqual(seen, {})
            self.assertFalse(Message.objects.exists())
            response = self.client.post(self.url, data, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            seen["range"]["thinking"], {"type": "enabled", "budget_tokens": 64}
        )
        self.assertEqual(seen["toggle"]["thinking"], {"type": "disabled"})
        self.assertNotIn("reasoning_effort", seen["e"])
        history = self.client.get(self.url).data["messages"]
        self.assertEqual(
            {
                str(row["model_id"]): row["reasoning_settings"]
                for row in history
                if row["role"] == "assistant"
            },
            settings,
        )

    def test_admin_inputs_and_invalid_configuration(self):
        self.sync(
            [
                {
                    "id": "e",
                    "reasoning_contract": "native_effort",
                    "reasoning_effort": ["raw"],
                }
            ]
        )
        model = self.model("e")
        form = CatalogModelForm(instance=model)
        self.assertEqual(form.initial["efforts"], ["raw"])
        self.assertEqual(form.initial["pin"], [])
        for override in [
            {"wire": "unverified-adapter"},
            {"default_effort": "missing"},
            {"budget_tokens": {"min": 80, "max": 30}},
            {"efforts": ["bad\nvalue"]},
            {"budget_presets": [True]},
            {"wire": "effort", "reasoning_toggle": True},
        ]:
            model.reasoning_overrides = override
            with self.subTest(override=override), self.assertRaises(ValidationError):
                model.full_clean()
        self.assertEqual(
            provider_facts({"reasoning_contract": ["invalid"]}, "compatible")["wire"],
            None,
        )

    def test_admin_change_form_pins_then_releases_individual_fields(self):
        from django.urls import reverse

        self.user.is_staff = self.user.is_superuser = True
        self.user.save()
        self.client.force_login(self.user)
        self.sync(
            [
                {
                    "id": "admin",
                    "reasoning_contract": "native_effort",
                    "reasoning_effort": ["low", "custom"],
                }
            ]
        )
        model = self.model("admin")
        url = reverse("admin:portal_languagemodel_change", args=[model.pk])

        def data():
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200)
            form = resp.context["adminform"].form
            fields = {}
            for bound in form.visible_fields():
                v = bound.value()
                if v is None or v is False:
                    continue
                fields[bound.name] = "on" if v is True else v
            return fields

        fields = data()
        fields.update(
            pin=["efforts", "wire"],
            efforts=["custom"],
            wire="router_effort",
            input_toman="2.1",
            output_toman="0",
        )
        response = self.client.post(url, fields)
        self.assertEqual(
            response.status_code,
            302,
            response.context["adminform"].form.errors if response.context else "",
        )
        model.refresh_from_db()
        self.assertEqual(
            model.reasoning_overrides, {"efforts": ["custom"], "wire": "router_effort"}
        )
        self.assertEqual(
            (model.input_price_per_million_rial, model.output_price_per_million_rial),
            (21, 0),
        )
        fields = data()
        fields["pin"] = ["wire"]
        self.assertEqual(self.client.post(url, fields).status_code, 302)
        model.refresh_from_db()
        self.assertEqual(model.reasoning_overrides, {"wire": "router_effort"})

    def test_router_model_descriptor_enables_only_declared_controls(self):
        row = {
            "id": "router",
            "supported_parameters": ["reasoning"],
            "reasoning": {
                "mandatory": False,
                "default_enabled": False,
                "supports_max_tokens": True,
                "supported_efforts": ["none", "high"],
            },
        }
        self.conn.discovery_type = "openrouter"
        self.conn.save()
        registry = {"router": {"budget_tokens": {"min": 64, "max": 256}}}
        self.sync([row], registry)
        model = self.model("router")
        p = runtime_model(model).reasoning_profile
        self.assertEqual(
            [c["type"] for c in p.controls], ["toggle", "effort", "budget"]
        )
        self.assertEqual(p.payload({"budget": 64}), {"reasoning": {"max_tokens": 64}})
        with self.assertRaises(ValidationError):
            p.payload({"toggle": True, "effort": "none"})
        row["reasoning"].pop("supports_max_tokens")
        self.sync([row], registry)
        self.assertNotIn(
            "budget",
            [
                c["type"]
                for c in runtime_model(self.model("router")).reasoning_profile.controls
            ],
        )

    def test_incomplete_and_contradictory_metadata_fail_closed(self):
        self.sync(
            [
                {
                    "id": "bad",
                    "reasoning_contract": "native_effort",
                    "reasoning_effort": ["custom"],
                    "supported_parameters": ["temperature"],
                },
                {
                    "id": "required",
                    "reasoning_contract": "native_effort",
                    "reasoning_options": [
                        {"type": "effort", "required": True, "values": []}
                    ],
                },
                {
                    "id": "negative",
                    "capabilities": {"reasoning": False},
                    "reasoning_contract": "toggle",
                    "reasoning_options": [{"type": "toggle"}],
                },
            ]
        )
        self.assertEqual(
            runtime_model(self.model("bad")).reasoning_profile.controls, []
        )
        p = runtime_model(self.model("required")).reasoning_profile
        with self.assertRaises(ValidationError):
            p.payload({})
        self.assertFalse(p.public()["available"])
        self.assertIs(
            runtime_model(self.model("negative")).reasoning_profile.supported, False
        )

    def test_leaf_descriptors_bind_types_ranges_and_wire(self):
        self.sync(
            [
                {
                    "id": "leaf",
                    "supported_parameters": [
                        {"name": "thinking.type", "options": ["enabled", "disabled"]},
                        {
                            "name": "thinking.budget_tokens",
                            "min": 16,
                            "max": 200,
                            "required": True,
                        },
                    ],
                }
            ]
        )
        p = runtime_model(self.model("leaf")).reasoning_profile
        self.assertEqual(p.public()["mode"], "combined")
        self.assertEqual(
            p.payload({"budget": 180}),
            {"thinking": {"type": "enabled", "budget_tokens": 180}},
        )
        with self.assertRaises(ValidationError):
            p.payload({})
        self.assertEqual(
            p.payload({"toggle": False}), {"thinking": {"type": "disabled"}}
        )

    def test_display_semantics_never_select_or_disable_a_wire_value(self):
        row = {
            "id": "mapping",
            "reasoning_contract": "toggle_effort",
            "reasoning_mandatory": True,
            "reasoning_options": [
                {
                    "type": "effort",
                    "values": [{"value": "off", "semantic_level": "disabled"}],
                }
            ],
        }
        self.sync([row])
        model = self.model("mapping")
        p = runtime_model(model).reasoning_profile
        self.assertEqual(
            p.payload({"effort": "off"}),
            {"thinking": {"type": "enabled"}, "reasoning_effort": "off"},
        )
        self.sync([{**row, "disabled_reasoning_efforts": ["off"]}])
        p = runtime_model(self.model("mapping")).reasoning_profile
        with self.assertRaises(ValidationError):
            p.payload({"effort": "off"})
