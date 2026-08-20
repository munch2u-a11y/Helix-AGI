import os
from PIL import Image, ImageSequence

def make_transparent_3d_mascot_gif():
    src_gif_path = '/home/nemo/Over_Agent_Design/web_ui/assets/helix_mascot_3d_animated.gif'
    dst_gif_path = '/home/nemo/Over_Agent_Design/web_ui/assets/helix_mascot_3d_transparent.gif'

    img = Image.open(src_gif_path)
    frames = []

    for frame in ImageSequence.Iterator(img):
        f = frame.convert('RGBA')
        datas = f.getdata()
        newData = []

        for item in datas:
            r, g, b, a = item
            brightness = int(0.299 * r + 0.587 * g + 0.114 * b)
            # Remove dark video background, keep 3D Helix mascot character
            if brightness < 35 and (r < 40 and g < 45 and b < 55):
                newData.append((r, g, b, 0))
            elif brightness < 50:
                alpha = int((brightness - 25) * 10)
                alpha = max(0, min(255, alpha))
                newData.append((r, g, b, alpha))
            else:
                newData.append((r, g, b, 255))

        f.putdata(newData)
        frames.append(f)

    # Save animated GIF with transparency
    frames[0].save(
        dst_gif_path,
        save_all=True,
        append_images=frames[1:],
        optimize=True,
        duration=img.info.get('duration', 66),
        loop=0,
        disposal=2
    )
    print("  ✓ Created 3D Animated Transparent Mascot GIF:", dst_gif_path)

if __name__ == '__main__':
    make_transparent_3d_mascot_gif()
