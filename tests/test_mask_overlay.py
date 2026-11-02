"""Unit tests for T8: Mask evidence overlay (meta_sam_parser decode + compositing)."""
from pathlib import Path
from unittest.mock import MagicMock
from PIL import Image
from stepproof.browser.vision_heal import SamVisionHealer
from stepproof import config as cfg


def test_sam_render_mask_overlay_with_valid_mask(tmp_path):
    healer = SamVisionHealer()
    # Create dummy base image
    base_img_path = tmp_path / "base.jpg"
    Image.new("RGB", (640, 480), (200, 200, 200)).save(base_img_path)

    det = MagicMock()
    det.box = (50, 50, 150, 100)
    det.conf = 0.9
    # Valid one_bit payload for 50x100
    # Create simple one_bit payload with meta_sam_parser
    det.mask = "x=0;y=0;c=0.9;data=50,100," + ("!" * 20)

    out_path = healer._render_mask_overlay(base_img_path, det, "Submit button")
    assert out_path is not None
    assert Path(out_path).exists()
    assert Path(out_path).stat().st_size > 0
    # Clean up test output
    try:
        Path(out_path).unlink()
    except Exception:
        pass


def test_sam_render_mask_overlay_fallback_to_box(tmp_path):
    healer = SamVisionHealer()
    base_img_path = tmp_path / "base.jpg"
    Image.new("RGB", (640, 480), (200, 200, 200)).save(base_img_path)

    # Det without mask payload
    det = MagicMock()
    det.box = (30, 40, 120, 80)
    det.conf = 0.85
    det.mask = None

    out_path = healer._render_mask_overlay(base_img_path, det, "Input field")
    assert out_path is not None
    assert Path(out_path).exists()
    assert Path(out_path).stat().st_size > 0
    try:
        Path(out_path).unlink()
    except Exception:
        pass
