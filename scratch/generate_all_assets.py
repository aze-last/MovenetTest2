import os
import numpy as np
from PIL import Image, ImageOps, ImageDraw

def generate():
    source_path = "C:/Users/ASUS/.gemini/antigravity/brain/f40f8369-c9ed-4758-9a8a-1b7282f7bf13/.user_uploaded/media_1793098252366_01c46aed.jpg"
    assert os.path.exists(source_path), "Source image does not exist!"

    orig_img = Image.open(source_path).convert("RGB")
    print(f"Original image size: {orig_img.size}")

    # Bounding box of content: 219, 31, 804, 543
    # 1. Full logo cropped to content with comfortable 16px margins
    crop_x1 = max(0, 219 - 16)
    crop_y1 = max(0, 31 - 16)
    crop_x2 = min(orig_img.width, 804 + 16)
    crop_y2 = min(orig_img.height, 543 + 16)
    full_cropped = orig_img.crop((crop_x1, crop_y1, crop_x2, crop_y2))
    
    # Save full banner
    full_banner_path = "monitor_app/assets/logo_full.png"
    full_cropped.save(full_banner_path, "PNG", optimize=True)
    print(f"Saved {full_banner_path} ({full_cropped.size})")

    # 2. Square Master Logo for profile & navbar (512x512)
    # Fit full_cropped into a 512x512 white/clean canvas with rounded corners or transparent
    # Let's create a transparent version using flood-fill from exterior corners
    rgba = orig_img.convert("RGBA")
    arr = np.array(rgba)
    h, w, _ = arr.shape
    
    from collections import deque
    visited = np.zeros((h, w), dtype=bool)
    q = deque([(0, 0), (0, w-1), (h-1, 0), (h-1, w-1)])
    for y, x in list(q):
        visited[y, x] = True

    while q:
        y, x = q.popleft()
        for dy, dx in [(-1,0), (1,0), (0,-1), (0,1)]:
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and not visited[ny, nx]:
                if np.all(arr[ny, nx, :3] >= 240):
                    visited[ny, nx] = True
                    q.append((ny, nx))

    # Exterior becomes transparent
    arr[visited, 3] = 0
    trans_img = Image.fromarray(arr)
    trans_cropped = trans_img.crop((crop_x1, crop_y1, crop_x2, crop_y2))
    
    # Center trans_cropped into 512x512
    square_logo = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    scale = 480 / max(trans_cropped.width, trans_cropped.height)
    new_w = int(trans_cropped.width * scale)
    new_h = int(trans_cropped.height * scale)
    scaled_content = trans_cropped.resize((new_w, new_h), Image.LANCZOS)
    paste_x = (512 - new_w) // 2
    paste_y = (512 - new_h) // 2
    square_logo.paste(scaled_content, (paste_x, paste_y), scaled_content)

    logo_path = "monitor_app/assets/logo.png"
    square_logo.save(logo_path, "PNG", optimize=True)
    print(f"Saved {logo_path} ({square_logo.size})")

    # Also copy to root assets/logo.png for spec compatibility
    root_logo_path = "assets/logo.png"
    os.makedirs("assets", exist_ok=True)
    square_logo.save(root_logo_path, "PNG", optimize=True)
    print(f"Saved {root_logo_path}")

    # 3. Emblem-only for Windows App Icon (.ico)
    # The emblem (eye + watchtowers) is from y=31 to y=420, x=219 to x=804
    emblem_crop = trans_img.crop((crop_x1, crop_y1, crop_x2, 422))
    emblem_square = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    scale_emb = 240 / max(emblem_crop.width, emblem_crop.height)
    ew = int(emblem_crop.width * scale_emb)
    eh = int(emblem_crop.height * scale_emb)
    scaled_emb = emblem_crop.resize((ew, eh), Image.LANCZOS)
    ex = (256 - ew) // 2
    ey = (256 - eh) // 2
    emblem_square.paste(scaled_emb, (ex, ey), scaled_emb)

    # Windows ICO multi-size (16, 24, 32, 48, 64, 128, 256)
    ico_path = "monitor_app/assets/app_icon.ico"
    icon_sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)]
    emblem_square.save(ico_path, format="ICO", sizes=icon_sizes)
    print(f"Saved {ico_path} with sizes {icon_sizes}")

    # Also save to root assets/app_icon.ico
    emblem_square.save("assets/app_icon.ico", format="ICO", sizes=icon_sizes)

    # 4. Inno Setup Modern Wizard Banner (WizardImageFile: 164x314 BMP)
    # Institutional gradient/solid dark background with the CellWatch eye, watchtower, and text
    wizard_banner = Image.new("RGB", (164, 314), (18, 26, 36)) # #121a24
    draw = ImageDraw.Draw(wizard_banner)
    # Draw subtle gradient or institutional header accent line
    draw.rectangle([0, 0, 164, 4], fill=(245, 158, 11)) # Amber accent bar
    draw.rectangle([0, 310, 164, 314], fill=(245, 158, 11))

    # Scale the full logo or emblem to fit nicely inside the 164px width (e.g. width=150)
    w_scale = 152 / full_cropped.width
    wb_w = int(full_cropped.width * w_scale)
    wb_h = int(full_cropped.height * w_scale)
    
    # Place on clean white card or composite with subtle border
    card = Image.new("RGB", (wb_w + 4, wb_h + 4), (255, 255, 255))
    card.paste(full_cropped.resize((wb_w, wb_h), Image.LANCZOS), (2, 2))
    
    banner_y = (314 - (wb_h + 4)) // 2
    banner_x = (164 - (wb_w + 4)) // 2
    wizard_banner.paste(card, (banner_x, banner_y))

    os.makedirs("installer", exist_ok=True)
    wizard_bmp_path = "installer/wizard_banner.bmp"
    wizard_banner.save(wizard_bmp_path, "BMP")
    print(f"Saved {wizard_bmp_path} ({wizard_banner.size})")

    # 5. Inno Setup Wizard Small Image (WizardSmallImageFile: 55x55 BMP)
    # Header logo at the top right of wizard pages
    small_img = Image.new("RGB", (55, 55), (255, 255, 255))
    scale_s = 51 / max(emblem_crop.width, emblem_crop.height)
    sw = int(emblem_crop.width * scale_s)
    sh = int(emblem_crop.height * scale_s)
    scaled_s = emblem_crop.resize((sw, sh), Image.LANCZOS)
    small_img.paste(scaled_s, ((55 - sw) // 2, (55 - sh) // 2), scaled_s)
    
    wizard_small_path = "installer/wizard_small.bmp"
    small_img.save(wizard_small_path, "BMP")
    print(f"Saved {wizard_small_path} ({small_img.size})")

    print("\nAll assets successfully generated!")

if __name__ == "__main__":
    generate()

