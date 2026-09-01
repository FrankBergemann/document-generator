from __future__ import annotations

import pytest
from pydantic import ValidationError

from cv_generator.models import Contact, Document, Link, Photo, Section


class TestPhoto:
    def test_data_uri_carries_the_bytes_and_the_type(self) -> None:
        photo = Photo(data=b"\x89PNG\r\n\x1a\n", media_type="image/png")
        assert photo.data_uri() == "data:image/png;base64,iVBORw0KGgo="

    def test_data_uri_needs_no_escaping_in_html(self) -> None:
        # base64's alphabet has no HTML-significant characters, which is why the
        # template can interpolate the URI with autoescape on.
        uri = Photo(data=bytes(range(256)), media_type="image/jpeg").data_uri()
        assert not set(uri) & set("<>&\"'")


class TestContact:
    def test_empty_by_default(self) -> None:
        assert Contact().is_empty()

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"email": "a@b.test"},
            {"phone": "+49 123"},
            {"location": "Berlin"},
            {"links": [Link(label="GitHub", url="https://x.test")]},
        ],
    )
    def test_any_field_makes_it_non_empty(self, kwargs: dict[str, object]) -> None:
        assert not Contact(**kwargs).is_empty()  # type: ignore[arg-type]


class TestDocument:
    def test_name_defaults_to_none(self) -> None:
        # A recipe with no Markdown source has no frontmatter to take a name
        # from, and no identity is still a valid document.
        assert Document().name is None

    def test_defaults(self) -> None:
        doc = Document(name="Ada")
        assert doc.lang == "de"
        assert doc.theme == "classic"
        assert doc.headline is None
        assert doc.photo is None
        assert doc.summary is None
        assert doc.sections == []
        assert doc.contact.is_empty()

    def test_unknown_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Document(name="Ada", nickname="typo")  # type: ignore[call-arg]

    def test_has_identity_is_false_when_completely_bare(self) -> None:
        assert Document().has_identity() is False

    def test_has_identity_is_true_with_a_name(self) -> None:
        assert Document(name="Ada").has_identity() is True

    def test_has_identity_is_true_with_only_a_headline(self) -> None:
        assert Document(headline="Mathematician").has_identity() is True

    def test_has_identity_is_true_with_only_contact_details(self) -> None:
        assert Document(contact=Contact(email="ada@example.com")).has_identity() is True

    def test_has_identity_is_true_with_only_a_photo(self) -> None:
        photo = Photo(data=b"\x89PNG\r\n\x1a\n", media_type="image/png")
        assert Document(photo=photo).has_identity() is True

    def test_section_lookup_by_slug(self) -> None:
        doc = Document(
            name="Ada", sections=[Section(title="Skills", slug="skills", markdown="- x")]
        )
        found = doc.section("skills")
        assert found is not None and found.title == "Skills"

    def test_section_lookup_misses_return_none(self) -> None:
        assert Document(name="Ada").section("skills") is None

    def test_default_containers_are_not_shared(self) -> None:
        first, second = Document(name="A"), Document(name="B")
        first.contact.links.append(Link(label="X", url="https://x.test"))
        assert second.contact.links == []
