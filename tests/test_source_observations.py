# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import asyncio
import hashlib
import urllib.request
from dataclasses import replace

import pytest
import rfc8785
from pydantic import ValidationError
from referencing.exceptions import Unresolvable

from powercontext.builtin.runtime.relational import _json_schema_validator, _validate_source_observation
from powercontext.builtin.sources import CONTENT_SOURCE_DEFINITION, ContentCapture
from powercontext.http import SourceDefinitionManifest as HttpSourceDefinitionManifest
from powercontext.http import SourceObservation as HttpSourceObservation
from powercontext.http import SubmitSourceObservationRequest
from powercontext.server.mapping import runtime_source_definition_manifest, submit_source_observation_request
from powercontext.sources import (
    TEXT_EVIDENCE_PROJECTION_KEY,
    MemoryEvidenceAuthority,
    MemoryEvidenceDeclaration,
    MemoryEvidenceVerification,
    Source,
    SourceCatalog,
    SourceDefinitionManifest,
    SourceDefinitionRegistry,
    SourceObservation,
    TextEvidence,
    manifest_for_definition,
    project_source_for_transport,
)


class EmptySourceBackend:
    async def list(self) -> tuple[Source, ...]:
        return ()

    async def get(self, source: Source, /) -> Source:
        raise AssertionError(source)


def test_definition_manifest_has_a_stable_content_addressed_identity() -> None:
    first = manifest_for_definition(CONTENT_SOURCE_DEFINITION)
    second = manifest_for_definition(CONTENT_SOURCE_DEFINITION)

    assert first == second
    assert first.fingerprint.startswith("sha256:")
    with pytest.raises(ValidationError, match="fingerprint does not match"):
        SourceDefinitionManifest.model_validate(first.model_dump(mode="json", by_alias=True) | {"version": "2"})


def test_definition_manifest_carries_versioned_memory_evidence_to_remote_observations() -> None:
    async def scenario() -> None:
        definition = replace(
            CONTENT_SOURCE_DEFINITION,
            memory_evidence=MemoryEvidenceDeclaration(
                authority=MemoryEvidenceAuthority.SYSTEM_ATTESTED,
                verification=MemoryEvidenceVerification.VERIFIED,
                declaration_version="attestation-v2",
            ),
        )
        registry = SourceDefinitionRegistry((definition,))
        manifest = manifest_for_definition(definition)
        source = await registry.resolve(ContentCapture(source_id="turn-1", content="Keep this declaration."))
        observation = project_source_for_transport(registry, source)

        assert manifest.memory_evidence == definition.memory_evidence
        assert source.memory_evidence == definition.memory_evidence
        assert observation.memory_evidence == definition.memory_evidence
        assert registry.memory_evidence(observation) == definition.memory_evidence
        assert manifest.fingerprint != manifest_for_definition(CONTENT_SOURCE_DEFINITION).fingerprint

        runtime = submit_source_observation_request(
            SubmitSourceObservationRequest(
                scope_id="scope",
                observation=HttpSourceObservation.model_validate(observation.model_dump(mode="json")),
            )
        )
        assert runtime.observation.memory_evidence == definition.memory_evidence
        _validate_source_observation(runtime.observation, manifest)

    asyncio.run(scenario())


def test_legacy_remote_definition_manifest_remains_neutral_and_accepted() -> None:
    current = manifest_for_definition(CONTENT_SOURCE_DEFINITION)
    legacy_payload = {
        "name": current.name,
        "version": current.version,
        "source_schema": current.source_schema,
        "projections": [projection.model_dump(mode="json", by_alias=True) for projection in current.projections],
    }
    legacy = SourceDefinitionManifest(
        name=current.name,
        version=current.version,
        source_schema=current.source_schema,
        projections=current.projections,
        fingerprint=f"sha256:{hashlib.sha256(rfc8785.dumps(legacy_payload)).hexdigest()}",
    )
    transported = HttpSourceDefinitionManifest.model_validate(
        legacy.model_dump(mode="json", by_alias=True, exclude={"memory_evidence"})
    )

    assert runtime_source_definition_manifest(transported) == legacy
    assert legacy.memory_evidence.authority == "untrusted"
    assert legacy.memory_evidence.verification == "unknown"

    async def legacy_source() -> SourceObservation:
        registry = SourceDefinitionRegistry((CONTENT_SOURCE_DEFINITION,))
        resolved = await registry.resolve(ContentCapture(source_id="turn-1", content="Legacy transport."))
        return project_source_for_transport(registry, resolved)

    source = asyncio.run(legacy_source()).model_copy(update={"definition_fingerprint": legacy.fingerprint})
    legacy_observation = HttpSourceObservation.model_validate(
        source.model_dump(mode="json", exclude={"memory_evidence"})
    )
    runtime_observation = submit_source_observation_request(
        SubmitSourceObservationRequest(scope_id="scope", observation=legacy_observation)
    ).observation
    assert "memory_evidence" not in runtime_observation.__pydantic_fields_set__
    _validate_source_observation(runtime_observation, legacy)


def test_source_observation_remains_usable_without_worker_definition_code() -> None:
    async def scenario() -> None:
        registry = SourceDefinitionRegistry((CONTENT_SOURCE_DEFINITION,))
        source = await registry.resolve(
            ContentCapture(source_id="turn-1", content="Keep the remote contract declarative.")
        )
        projected = project_source_for_transport(registry, source)
        catalog = SourceCatalog(backend=EmptySourceBackend())
        payload = await catalog.read(projected)
        projection = catalog.project(projected, TEXT_EVIDENCE_PROJECTION_KEY)

        assert isinstance(projected, SourceObservation)
        assert catalog.as_ref(projected).model_dump() == {"source_type": "content", "source_id": "turn-1"}
        assert payload == projected.payload
        assert catalog.projection_keys(projected) == (TEXT_EVIDENCE_PROJECTION_KEY,)
        assert registry.project(projected, TEXT_EVIDENCE_PROJECTION_KEY) == projection
        assert TextEvidence.model_validate(projection).content == "Keep the remote contract declarative."

    asyncio.run(scenario())


def test_remote_source_observation_requires_captured_materialization() -> None:
    async def scenario() -> None:
        registry = SourceDefinitionRegistry((CONTENT_SOURCE_DEFINITION,))
        source = await registry.resolve(ContentCapture(source_id="turn-1", content="Retain this value."))
        observation = project_source_for_transport(registry, source)

        with pytest.raises(ValidationError):
            SourceObservation.model_validate(observation.model_dump(mode="json") | {"materialization": "referenced"})

    asyncio.run(scenario())


def test_remote_schema_references_are_rejected_without_network_access(monkeypatch: pytest.MonkeyPatch) -> None:
    attempted = False

    def reject_request(*_args: object, **_kwargs: object) -> None:
        nonlocal attempted
        attempted = True
        raise OSError("network access is forbidden")  # noqa: TRY003

    monkeypatch.setattr(urllib.request, "urlopen", reject_request)
    validator = _json_schema_validator("remote", {"$ref": "http://127.0.0.1:9/schema"})

    with pytest.raises(Unresolvable):
        validator.validate({})
    assert not attempted

    with pytest.raises(ValidationError, match="remote schema references are not allowed"):
        SourceDefinitionManifest(
            name="remote",
            version="1",
            fingerprint=f"sha256:{'0' * 64}",
            source_schema={"$dynamicRef": "https://example.invalid/schema"},
        )
