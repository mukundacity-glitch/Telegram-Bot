from PIL import Image, ImageChops, ImageOps
from vortex import brand_footer as brand


def test_pinned_branding_respects_reserved_geometry():
    canvas=Image.new("RGB",(1536,864),"#FFFFFF")
    before=canvas.copy()
    brand.approved_sell_logo(canvas,box=(0,0,290,91),matte="#FFFFFF")
    brand.approved_social_footer(canvas,reserved_height=64)
    assert ImageChops.difference(canvas.crop((0,91,1536,800)),
                                 before.crop((0,91,1536,800))).getbbox() is None
    logo=brand._approved_asset(brand.SELL_LOGO,"a6871f20a9a901570df252a24496b445881dd86b")
    logo=ImageOps.contain(logo,(266,75),Image.Resampling.LANCZOS)
    x,y=(290-logo.width)//2,(91-logo.height)//2
    assert ImageChops.difference(canvas.crop((x,y,x+logo.width,y+logo.height)),logo).getbbox() is None
    footer=brand._approved_asset(brand.SELL_FOOTER,"2f78e78c6bf29b02df6b10a505485bca2f95842f")
    footer=ImageOps.contain(footer,(1536,64),Image.Resampling.LANCZOS)
    x,y=(1536-footer.width)//2,800+(64-footer.height)//2
    assert ImageChops.difference(canvas.crop((x,y,x+footer.width,y+footer.height)),footer).getbbox() is None
