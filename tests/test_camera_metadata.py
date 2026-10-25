"""Actual Starlink metadata must not turn a plot or Blender render into a photograph."""
from studio import media


def test_actual_starlink_plot_and_render_do_not_count_as_photos(monkeypatch):
    # Public metadata retained by producer40160034587; the filename alone misses both.
    rows = [
        ("File:Download picture.png", "updated starlink plot data", "Own work"),
        ("File:Starlink 01.webp", "Starlink satellite",
         "Own work rendered with Blender and a model from Sketchfab (CC-BY-4.0)"),
        ("File:Starlink pole mounted antenna.webp", "Starlink pole mount", "Own work"),
        ("File:Volodymyr Zelensky Official portrait.jpg", "Volodymyr Zelensky", "Own work"),
    ]
    info = {name: {"width": 1600, "height": 1200, "mime": "image/jpeg", "url": "https://example.test/image",
                   "descriptionurl": "https://commons.wikimedia.org/", "sha1": str(i),
                   "extmetadata": {"LicenseShortName": {"value": "CC BY 4.0"},
                                   "ImageDescription": {"value": desc}, "Credit": {"value": credit}}}
            for i, (name, desc, credit) in enumerate(rows)}
    monkeypatch.setattr(media, "_info", lambda files: {f: info[f] for f in files})
    picked = media.picks(list(info))
    assert [p.file for p in picked] == [rows[2][0], rows[3][0]]
    assert all(p.license == "CC BY 4.0" for p in picked)
    assert not media.NOT_CAMERA.search("A photo of a Blender demonstration at a computer lab")
    assert not media.NOT_CAMERA.search("A photograph of a 3D printed satellite model")
