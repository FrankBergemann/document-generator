from __future__ import annotations

import pytest
from pydantic import ValidationError

from cv_generator.models import CV, Contact, Link, Photo, Section


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


class TestCV:
    def test_name_is_required(self) -> None:
        with pytest.raises(ValidationError):
            CV()  # type: ignore[call-arg]

    def test_defaults(self) -> None:
        cv = CV(name="Ada")
        assert cv.lang == "de"
        assert cv.theme == "classic"
        assert cv.headline is None
        assert cv.photo is None
        assert cv.summary is None
        assert cv.sections == []
        assert cv.contact.is_empty()

    def test_unknown_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CV(name="Ada", nickname="typo")  # type: ignore[call-arg]

    def test_section_lookup_by_slug(self) -> None:
        cv = CV(name="Ada", sections=[Section(title="Skills", slug="skills", markdown="- x")])
        found = cv.section("skills")
        assert found is not None and found.title == "Skills"

    def test_section_lookup_misses_return_none(self) -> None:
        assert CV(name="Ada").section("skills") is None

    def test_default_containers_are_not_shared(self) -> None:
        first, second = CV(name="A"), CV(name="B")
        first.contact.links.append(Link(label="X", url="https://x.test"))
        assert second.contact.links == []
