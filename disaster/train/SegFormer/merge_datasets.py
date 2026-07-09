import os
import numpy as np
from PIL import Image, ImageDraw
import yaml
import shutil
from collections import defaultdict
import random

random.seed(42)
np.random.seed(42)

BASE = r'd:\zhinengruanjianlingyu2'
OUTPUT = os.path.join(BASE, 'mergedata')
TEMP = os.path.join(BASE, 'mergedata_temp')

# Pixel values
PIPE_PIXEL = 1
CONSTRUCTION_PIXEL = 2

# Clean output and temp
for d in [OUTPUT, TEMP]:
    if os.path.isdir(d):
        shutil.rmtree(d)
os.makedirs(TEMP, exist_ok=True)

# Global counter for unique names
img_counter = [0]

def get_img_dims(img_path):
    with Image.open(img_path) as im:
        return im.size  # (W, H)

def polygon_to_mask(coords, img_w, img_h):
    pixels = []
    for i in range(1, len(coords), 2):
        pixels.extend([coords[i] * img_w, coords[i+1] * img_h])
    return pixels

def bbox_to_mask_polygon(bbox, img_w, img_h):
    cx, cy, w, h = bbox[1], bbox[2], bbox[3], bbox[4]
    x1, y1 = (cx - w/2) * img_w, (cy - h/2) * img_h
    x2, y2 = (cx + w/2) * img_w, (cy + h/2) * img_h
    return [x1, y1, x1, y2, x2, y2, x2, y1]

def draw_polygon(draw, pixels, val):
    pts = [(pixels[i], pixels[i+1]) for i in range(0, len(pixels), 2)]
    if len(pts) >= 3:
        draw.polygon(pts, fill=val)
    elif len(pts) == 2:
        draw.line(pts, fill=val, width=3)

def is_bbox(parts):
    return len(parts) == 5

def process_yolo(ds_path, ds_name, split_dirs, class_mapping, collected):
    """
    Process YOLO dataset into temp pool.
    collected: list of (img_path_to_copy, mask_pil, class_label)
    class_label: 'pipe' or 'construction_area'
    """
    has_dirs = False

    for split_name, subdir in split_dirs.items():
        images_dir = os.path.join(ds_path, subdir, 'images')
        labels_dir = os.path.join(ds_path, subdir, 'labels')

        if not os.path.isdir(images_dir) or not os.path.isdir(labels_dir):
            images_dir2 = os.path.join(ds_path, 'images')
            labels_dir2 = os.path.join(ds_path, 'labels')
            if os.path.isdir(images_dir2) and os.path.isdir(labels_dir2):
                images_dir = images_dir2
                labels_dir = labels_dir2
            else:
                continue

        has_dirs = True
        print(f'  [{ds_name}] scanning {images_dir}')

        for img_file in sorted(os.listdir(images_dir)):
            if not img_file.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp')):
                continue

            img_path = os.path.join(images_dir, img_file)
            base_name = os.path.splitext(img_file)[0]
            label_path = os.path.join(labels_dir, base_name + '.txt')

            try:
                img_w, img_h = get_img_dims(img_path)
            except:
                continue

            mask = Image.new('L', (img_w, img_h), 0)
            draw = ImageDraw.Draw(mask)
            has_labels = False
            present_classes = set()

            if os.path.isfile(label_path):
                with open(label_path, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        parts = line.split()
                        if len(parts) < 5:
                            continue
                        try:
                            cls = int(float(parts[0]))
                        except:
                            continue
                        if cls not in class_mapping:
                            continue

                        pval = class_mapping[cls]
                        if is_bbox(parts):
                            poly = bbox_to_mask_polygon(
                                [cls, float(parts[1]), float(parts[2]),
                                 float(parts[3]), float(parts[4])], img_w, img_h)
                        else:
                            poly = polygon_to_mask([float(x) for x in parts], img_w, img_h)

                        if len(poly) >= 4:
                            draw_polygon(draw, poly, pval)
                            has_labels = True
                            if pval == PIPE_PIXEL:
                                present_classes.add('pipe')
                            elif pval == CONSTRUCTION_PIXEL:
                                present_classes.add('construction_area')

            if not has_labels:
                continue

            # Determine dominant class for stratification
            # Since user said each image has only one class, use that
            if 'pipe' in present_classes and 'construction_area' in present_classes:
                cls_label = 'mixed'
            elif 'pipe' in present_classes:
                cls_label = 'pipe'
            else:
                cls_label = 'construction_area'

            collected.append((img_path, mask, cls_label))

    return has_dirs


def process_png_mask(ds_path, ds_name, split_dirs, class_mapping, collected):
    """
    Process PNG semantic segmentation dataset into temp pool.
    """
    has_dirs = False

    for split_name, subdir in split_dirs.items():
        src_dir = os.path.join(ds_path, subdir)
        if not os.path.isdir(src_dir):
            continue
        has_dirs = True
        print(f'  [{ds_name}] scanning {src_dir}')

        files = sorted(os.listdir(src_dir))
        img_files = [f for f in files if not f.endswith('_mask.png') and
                     f.lower().endswith(('.jpg', '.jpeg', '.png'))]

        for img_file in img_files:
            img_path = os.path.join(src_dir, img_file)
            base_name = os.path.splitext(img_file)[0]

            # Find mask
            mask_file = None
            if os.path.isfile(os.path.join(src_dir, base_name + '_mask.png')):
                mask_file = base_name + '_mask.png'
            else:
                for f in files:
                    if f.endswith('_mask.png') and f.replace('_mask.png', '') == base_name:
                        mask_file = f
                        break
            if mask_file is None:
                continue

            mask_path = os.path.join(src_dir, mask_file)
            try:
                mask_img = Image.open(mask_path)
                mask_arr = np.array(mask_img)
                new_mask = np.zeros_like(mask_arr, dtype=np.uint8)

                for old_val, new_val in class_mapping.items():
                    new_mask[mask_arr == old_val] = new_val

                if np.max(new_mask) == 0:
                    continue

                present_vals = set(np.unique(new_mask)) - {0}
                if PIPE_PIXEL in present_vals and CONSTRUCTION_PIXEL in present_vals:
                    cls_label = 'mixed'
                elif PIPE_PIXEL in present_vals:
                    cls_label = 'pipe'
                else:
                    cls_label = 'construction_area'

                mask_pil = Image.fromarray(new_mask)
                collected.append((img_path, mask_pil, cls_label))
            except Exception as e:
                print(f'    ERROR {img_path}: {e}')

    return has_dirs


# =========================  Phase 1: Collect =========================
print('=== Phase 1: 收集所有数据到临时池 ===\n')
collected = []  # list of (img_path, mask_pil, class_label)

# 1. Combined Pipe.v3i.yolov8: class 0 → pipe
print('[1/8] Combined Pipe.v3i.yolov8')
process_yolo(os.path.join(BASE, 'Combined Pipe.v3i.yolov8'), 'CombinedPipe',
             {'train': 'train', 'valid': 'valid', 'test': 'test'},
             {0: PIPE_PIXEL}, collected)

# 2. pipe-detection.v3i.yolov12: class 0 → pipe
print('[2/8] pipe-detection.v3i.yolov12')
process_yolo(os.path.join(BASE, 'pipe-detection.v3i.yolov12'), 'pipe_detect_v12',
             {'train': 'train'},
             {0: PIPE_PIXEL}, collected)

# 3. pipe.v1i.yolov8: class 0 → pipe
print('[3/8] pipe.v1i.yolov8')
process_yolo(os.path.join(BASE, 'pipe.v1i.yolov8'), 'pipe_v1',
             {'train': 'train', 'valid': 'valid', 'test': 'test'},
             {0: PIPE_PIXEL}, collected)

# 4. pipe.v2i.png-mask-semantic: pixel 1 → pipe
print('[4/8] pipe.v2i.png-mask-semantic')
process_png_mask(os.path.join(BASE, 'pipe.v2i.png-mask-semantic'), 'pipe_v2_semantic',
                 {'train': 'train', 'valid': 'valid', 'test': 'test'},
                 {1: PIPE_PIXEL}, collected)

# 5. pipes.v4i.yolov8: classes 0-7 → pipe
print('[5/8] pipes.v4i.yolov8')
process_yolo(os.path.join(BASE, 'pipes.v4i.yolov8'), 'pipes_v4',
             {'train': 'train', 'valid': 'valid', 'test': 'test'},
             {0: PIPE_PIXEL, 1: PIPE_PIXEL, 2: PIPE_PIXEL, 3: PIPE_PIXEL,
              4: PIPE_PIXEL, 5: PIPE_PIXEL, 6: PIPE_PIXEL, 7: PIPE_PIXEL},
             collected)

# 6. pipe (no version): class 4 → pipe
print('[6/8] pipe (no version)')
process_yolo(os.path.join(BASE, 'pipe'), 'pipe_noversion',
             {'train': ''},
             {4: PIPE_PIXEL}, collected)

# 7. construction_area1: class 0 → construction_area
print('[7/8] construction_area1')
process_yolo(os.path.join(BASE, 'construction_area1'), 'ca1',
             {'train': ''},
             {0: CONSTRUCTION_PIXEL}, collected)

# 8. construction_area2: class 0 → construction_area
print('[8/8] construction_area2')
process_yolo(os.path.join(BASE, 'construction_area2'), 'ca2',
             {'train': ''},
             {0: CONSTRUCTION_PIXEL}, collected)

print(f'\n收集完成: 共 {len(collected)} 张有效图像')

# =========================  Phase 2: Stratified Split =========================
print('\n=== Phase 2: 分层划分 (80%/10%/10%) ===\n')

# Separate by class label
pipe_data = [d for d in collected if d[2] == 'pipe']
ca_data = [d for d in collected if d[2] == 'construction_area']
mixed_data = [d for d in collected if d[2] == 'mixed']

print(f'  纯管道(pipe): {len(pipe_data)} 张')
print(f'  纯施工区(construction_area): {len(ca_data)} 张')
if mixed_data:
    print(f'  混合(mixed): {len(mixed_data)} 张')

def stratified_split(data_list):
    """Split a list into train(80%), valid(10%), test(10%) deterministically."""
    n = len(data_list)
    if n == 0:
        return [], [], []
    indices = list(range(n))
    random.shuffle(indices)
    n_train = int(n * 0.8)
    n_valid = int(n * 0.1)
    # Adjust so that train+valid+test = n
    train_idx = set(indices[:n_train])
    valid_idx = set(indices[n_train:n_train + n_valid])
    test_idx = set(indices[n_train + n_valid:])
    return train_idx, valid_idx, test_idx

pipe_train_idx, pipe_valid_idx, pipe_test_idx = stratified_split(pipe_data)
ca_train_idx, ca_valid_idx, ca_test_idx = stratified_split(ca_data)
mixed_train_idx, mixed_valid_idx, mixed_test_idx = stratified_split(mixed_data)

# Assign splits
splits = {'train': [], 'valid': [], 'test': []}

for i, d in enumerate(pipe_data):
    if i in pipe_train_idx:
        splits['train'].append(d)
    elif i in pipe_valid_idx:
        splits['valid'].append(d)
    else:
        splits['test'].append(d)

for i, d in enumerate(ca_data):
    if i in ca_train_idx:
        splits['train'].append(d)
    elif i in ca_valid_idx:
        splits['valid'].append(d)
    else:
        splits['test'].append(d)

for i, d in enumerate(mixed_data):
    if i in mixed_train_idx:
        splits['train'].append(d)
    elif i in mixed_valid_idx:
        splits['valid'].append(d)
    else:
        splits['test'].append(d)

# Shuffle within each split
for s in splits:
    random.shuffle(splits[s])

# Print split summary
for s in ['train', 'valid', 'test']:
    total = len(splits[s])
    p = sum(1 for d in splits[s] if d[2] == 'pipe')
    c = sum(1 for d in splits[s] if d[2] == 'construction_area')
    m = sum(1 for d in splits[s] if d[2] == 'mixed')
    pct = total / len(collected) * 100 if collected else 0
    print(f'  {s}: 总数={total} ({pct:.1f}%)  管道={p}  施工区={c}  混合={m}')

# =========================  Phase 3: Save to disk =========================
print('\n=== Phase 3: 保存到 mergedata ===')

for s in ['train', 'valid', 'test']:
    os.makedirs(os.path.join(OUTPUT, s, 'images'), exist_ok=True)
    os.makedirs(os.path.join(OUTPUT, s, 'masks'), exist_ok=True)

counter = 0
for s in ['train', 'valid', 'test']:
    print(f'  保存 {s} 中... ({len(splits[s])} 张)')
    for img_path, mask_pil, cls_label in splits[s]:
        new_name = f'img_{counter:06d}'
        out_img = os.path.join(OUTPUT, s, 'images', new_name + '.jpg')
        out_mask = os.path.join(OUTPUT, s, 'masks', new_name + '_mask.png')

        # Copy and convert image
        try:
            with Image.open(img_path) as im:
                im.convert('RGB').save(out_img, 'JPEG', quality=95)
        except Exception as e:
            print(f'    ERROR saving image: {img_path}: {e}')
            continue

        mask_pil.save(out_mask, 'PNG')
        counter += 1

        if counter % 500 == 0:
            print(f'    已保存 {counter} 张...')

print(f'\n  总计保存: {counter} 张')

# =========================  Write data.yaml =========================
yaml_path = os.path.join(OUTPUT, 'data.yaml')
yaml_content = {
    'path': OUTPUT,
    'train': 'train/images',
    'val': 'valid/images',
    'test': 'test/images',
    'nc': 2,
    'names': ['pipe', 'construction_area']
}
with open(yaml_path, 'w') as f:
    yaml.dump(yaml_content, f, default_flow_style=False, allow_unicode=True)

# Clean up temp
if os.path.isdir(TEMP):
    shutil.rmtree(TEMP)

print(f'\n=== 完成! ===')
print(f'data.yaml 已生成: {yaml_path}')
print(f'类别: 0=background, 1=pipe, 2=construction_area')
