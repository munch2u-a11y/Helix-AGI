import os
from PIL import Image

def extract_and_clean_sprites():
    src_path = '/home/nemo/.gemini/antigravity/brain/87e566e8-d31f-4cbd-95f5-b6af95130e70/media__1787236409496.jpg'
    out_dir = '/home/nemo/Over_Agent_Design/web_ui/assets'
    os.makedirs(out_dir, exist_ok=True)

    img = Image.open(src_path).convert('RGBA')

    crops = {
        'helix_guy_thinking.png': (40, 20, 240, 385),
        'helix_guy_happy.png': (235, 20, 420, 385),
        'helix_guy_joy.png': (415, 0, 605, 395),
        'helix_guy_focused.png': (600, 20, 785, 385),
        'helix_guy_surprised.png': (780, 20, 965, 385)
    }

    for name, bbox in crops.items():
        crop_img = img.crop(bbox)
        datas = crop_img.getdata()
        
        newData = []
        for item in datas:
            r, g, b, a = item
            brightness = int(0.299 * r + 0.587 * g + 0.114 * b)
            # Make dark background pixels transparent
            if brightness < 30 and (g < 45 and b < 50):
                newData.append((r, g, b, 0))
            elif brightness < 45:
                alpha = int((brightness - 20) * 10)
                alpha = max(0, min(255, alpha))
                newData.append((r, g, b, alpha))
            else:
                newData.append((r, g, b, 255))
                
        crop_img.putdata(newData)
        save_path = os.path.join(out_dir, name)
        crop_img.save(save_path, 'PNG')
        print(f"  ✓ Saved transparent mascot sprite: {name} ({crop_img.size})")

if __name__ == '__main__':
    extract_and_clean_sprites()
