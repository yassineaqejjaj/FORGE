"""PII detector (port of ORBIT): types, validators, overlaps, masking."""

from __future__ import annotations

import pytest

from forge.domain.enums import PiiType
from forge.domain.rules import pii


def types(text: str) -> list[PiiType]:
    return [e.type for e in pii.detect_pii(text)]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("contact: marie.curie@example.fr", PiiType.EMAIL),
        ("Appelez le 06 12 34 56 78", PiiType.PHONE),
        ("ou le +33 6 12 34 56 78", PiiType.PHONE),
        ("international +44 20 7946 0958", PiiType.PHONE),
        ("IBAN FR76 3000 6000 0112 3456 7890 189", PiiType.IBAN),
        ("carte 4111 1111 1111 1111", PiiType.CARD),
        ("NIR 1 85 05 78 006 084 91", PiiType.NIR),
        ("serveur 192.168.10.42", PiiType.IP),
        ("Rendez-vous avec Mme Dupont demain", PiiType.PERSON),
    ],
)
def test_detects_each_type(text: str, expected: PiiType) -> None:
    assert expected in types(text)


def test_checksums_reject_invalid_numbers() -> None:
    assert PiiType.IBAN not in types("FR76 3000 6000 0112 3456 7890 188")
    assert PiiType.CARD not in types("4111 1111 1111 1112")
    assert not pii.nir_is_valid("185057800608436")
    assert pii.iban_is_valid("FR7630006000011234567890189")
    assert pii.luhn_is_valid("4111111111111111")


def test_no_false_positives_on_plain_text() -> None:
    assert types("Version 1.2.3 livrée le 12/03, 45 tickets traités, Madame la Directrice.") == []


def test_overlaps_resolved_by_priority() -> None:
    entities = pii.detect_pii("IBAN FR7630006000011234567890189")
    assert [e.type for e in entities] == [PiiType.IBAN]


def test_redaction_and_labels() -> None:
    result = pii.analyze("Écrire à paul@example.com")
    assert result.redacted == "Écrire à [EMAIL]"
    assert result.counts == {"EMAIL": 1}
    assert set(pii.PII_LABELS) == set(PiiType)


def test_mask_never_reveals_full_value() -> None:
    assert pii.mask("jean.dupont@example.com") == "j•••@e•••.com"
    masked = pii.mask("06 12 34 56 78")
    assert masked.startswith("06") and "34 56" not in masked
    assert pii.mask("abc") == "•••"
