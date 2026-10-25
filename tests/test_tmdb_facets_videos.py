from tool.tmdb.normalize.facets import videos


def test_trailers_come_before_teasers_when_only_a_few_videos_are_shown() -> None:
    results = [{"name": f"teaser {n}", "type": "Teaser", "site": "YouTube", "key": f"t{n}", "official": True} for n in range(8)]
    results.append({"name": "Official Trailer", "type": "Trailer", "site": "YouTube", "key": "tr", "official": False})
    shown, total = videos({"results": results})["videos"]
    assert total == 9 and shown[0]["name"] == "Official Trailer"
