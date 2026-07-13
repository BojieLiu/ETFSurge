from PIL import Image, ImageDraw, ImageFilter

SIZES = [256, 128, 64, 48, 32, 16]
NAVY = (18, 28, 46)
CYAN = (0, 212, 255)
GOLD = (255, 200, 50)
WHITE = (255, 255, 255)


def gen_icon_img(size):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = cy = size // 2
    r = size // 2 - size // 16

    # 背景圆 - 渐变感通过多层圆实现
    for i in range(6):
        radius = int(r - i * r * 0.03)
        alpha = 255 - i * 20
        d.ellipse(
            [cx - radius, cy - radius, cx + radius, cy + radius],
            fill=(*NAVY, max(alpha, 80)),
        )

    # 外圈发光描边
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=CYAN, width=max(2, size // 48))

    # 波浪曲线 (破浪意象)
    wave_color = CYAN
    points = []
    for i in range(41):
        t = i / 40
        x = cx - int(r * 0.6) + int(r * 1.2 * t)
        # 波浪: 从底部上升, 中间两次起伏, 结尾上扬
        wave_y = 0.75 - 0.55 * t + 0.12 * (t * 2 - 1) ** 2
        y = cy - int(r * wave_y)
        points.append((x, y))

    # 主浪 - 粗线 + 发光
    for w, clr in [(max(3, size // 20), CYAN), (max(2, size // 32), (100, 230, 255))]:
        d.line(points, fill=clr, width=w)

    # 浪尖点缀 (冲浪感)
    tip_x, tip_y = points[-1]
    arrow_size = max(4, size // 20)
    d.polygon(
        [
            (tip_x + arrow_size, tip_y),
            (tip_x - arrow_size // 2, tip_y - arrow_size),
            (tip_x - arrow_size // 2, tip_y + arrow_size),
        ],
        fill=GOLD,
    )

    return img


icons = [gen_icon_img(s) for s in SIZES]
icons[0].save(
    "etf_surge.ico",
    format="ICO",
    sizes=[(s, s) for s in SIZES],
    append_images=icons[1:],
)
print("Icon saved: etf_surge.ico")
