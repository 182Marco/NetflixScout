from tool.tmdb.normalize.facets import videos


def test_trailers_come_before_teasers_when_only_a_few_videos_are_shown() -> None:
    results = [{"name": f"teaser {n}", "type": "Teaser", "site": "YouTube", "key": f"t{n}", "official": True} for n in range(8)]
    results.append({"name": "Official Trailer", "type": "Trailer", "site": "YouTube", "key": "tr", "official": False})
    shown, total = videos({"results": results})["videos"]
    assert total == 9 and shown[0]["name"] == "Official Trailer"


def test_list_cards_carry_the_release_date_but_detail_cards_do_not_duplicate_it() -> None:
    from tool.tmdb.models.results import Entity
    from tool.tmdb.prompt_budget import card_text

    listed = Entity(kind="movie", tmdb_id=1, title="Upcoming", year=2026, release_date="2026-10-30")
    assert "uscita 2026-10-30" in card_text(listed)
    detail = Entity(kind="movie", tmdb_id=1, title="Upcoming", year=2026, release_date="2026-10-30",
                    essentials={"release_date": "2026-10-30"})
    assert "uscita" not in card_text(detail)
    undated = Entity(kind="movie", tmdb_id=2, title="Undated")
    assert "uscita" not in card_text(undated)


def test_date_dependent_operations_tell_the_model_what_day_it_is() -> None:
    import datetime

    from tool.tmdb.models.results import RequestOutcome
    from tool.tmdb.prompt_budget import pack_context

    today = datetime.date.today().isoformat()
    for operation in ("chart", "discover_movies", "discover_tv"):
        packed = pack_context([RequestOutcome(operation=operation)], api_language="it-IT", status="ok")
        assert packed.metadata["today"] == today
    plain = pack_context([RequestOutcome(operation="movie_details")], api_language="it-IT", status="ok")
    assert "today" not in plain.metadata
