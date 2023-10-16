import logging
import random
import warnings
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Union

import cv2
import tqdm
from waffle_utils.file import io

from waffle_hub import TaskType
from waffle_hub.schema.fields import Annotation, Category, Image


def _generate_random_color_code(num_colors):
    color_codes = []
    for _ in range(num_colors):
        # 무작위 RGB 값을 생성합니다.
        red = random.randint(0, 255)
        green = random.randint(0, 255)
        blue = random.randint(0, 255)

        # RGB 값을 16진수로 변환하여 색상 코드를 생성합니다.
        color_code = f"#{red:02X}{green:02X}{blue:02X}"

        color_codes.append(color_code)

    return color_codes


def export_superb_ai(self, export_dir: Union[str, Path]) -> str:
    """Export dataset to SuperbAI format
    Args:
        export_dir (Path): Path to export directory

    Returns:
        str: Path to export directory
    """
    logging.info(f"Exporting.. SuperAi Dataset.")
    export_dir = Path(export_dir)
    io.make_directory(export_dir)

    image_dir = export_dir / "images"
    meta_dir = export_dir / "meta"
    label_dir = export_dir / "labels"

    io.make_directory(image_dir)
    io.make_directory(meta_dir)
    io.make_directory(label_dir)

    num_colors = len(self.get_categories())
    colors = _generate_random_color_code(num_colors)

    super_cats = defaultdict(list)
    [
        super_cats[category.supercategory].append(category.name)
        for i, category in enumerate(self.get_categories())
    ]

    object_classes = []
    check_lst = []
    for i, category in enumerate(self.get_categories()):
        if category.supercategory not in check_lst:
            check_lst.append(category.supercategory)
            object_classes.append(
                {
                    "id": category.category_id,
                    "name": category.supercategory,
                    "color": colors[i],
                    "properties": [],
                    "constraints": {},
                    "ai_class_map": [],
                    "annotation_type": "box",
                }
            )

    options = []
    for object in object_classes:
        if len(super_cats[object["name"]]) == 1:
            object["properties"] = []
        else:
            for option_name in super_cats[object["name"]]:
                options.append(
                    {"id": category.category_id, "name": option_name},
                )
            object["properties"] = [
                {
                    "id": category.category_id,
                    "name": f"{object['name']}_Type",
                    "type": "checkbox",
                    "options": options,
                    "required": True,
                    "description": "",
                    "render_value": False,
                    "default_value": [],
                }
            ]

    project = {
        "type": "image-siesta",  # Unknown
        "version": "0.6.5",  # Unknown
        "data-type": "image",  # Unknown
        "categorization": {"properties": []},
        TaskType.OBJECT_DETECTION.name.lower(): {
            "keypoints": [],
            "object_groups": [],
            "object_classes": object_classes,
            "annotation_types": ["box"],
        },
    }
    io.save_json(project, str(export_dir / "project.json"), create_directory=True)

    for image in self.get_images():
        image_path = self.raw_image_dir / image.file_name
        image_dst_path = image_dir / image.file_name
        io.copy_file(image_path, image_dst_path, create_directory=True)

        meta_path = f"{meta_dir}/{image.file_name}.json"
        label_path = f"{label_dir}/{image.image_id}.json"

        meta = {
            "data_key": f"images/{image.file_name}",
            "dataset": self.get_dataset_info().name,
            "image_info": {"width": image.width, "height": image.height},
            "label_id": image.image_id,
            "label_path": [f"labels/{image.image_id}.json"],
            "last_updated_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "tags": [],
            "work_assignee": "research@snuailab.ai",
            "status": "Waffle_dataset to Sueprb AI Dataset",
        }
        io.save_json(meta, Path(meta_dir) / meta_path)

        label_lst = []
        for i, annotation in enumerate(self.get_annotations(image.image_id)):
            supercategory = self.get_categories([annotation.category_id])[0].supercategory
            category = self.get_categories([annotation.category_id])[0].name

            if supercategory == category:
                properties = []
            else:
                properties = [
                    {
                        "type": "checkbox",
                        "property_id": annotation.category_id,
                        "property_name": f"{supercategory}_Type",
                        "option_names": [self.get_categories([annotation.category_id])[0].name],
                    }
                ]

            label_lst.append(
                {
                    "id": annotation.annotation_id,
                    "class_id": annotation.category_id,
                    "class_name": self.get_categories([annotation.category_id])[0].supercategory,
                    "annotation_type": "box",
                    "annotation": {
                        "coord": {
                            "x": annotation.bbox[0],
                            "y": annotation.bbox[1],
                            "width": annotation.bbox[2],
                            "height": annotation.bbox[3],
                        },
                        "meta": {
                            "z_index": i,
                            "visible": True,
                            "alpha": 1,
                            "color": colors[annotation.category_id - 1],
                        },
                    },
                    "properties": properties,
                }
            )
        label_json = {"objects": label_lst}
        io.save_json(label_json, label_path, create_directory=True)

    logging.info(f"Exported SuperAi Dataset. Export_dir Path: {export_dir}")

    return str(export_dir)


def _get_superb_det_categories(self, superb_project, type):
    superb_cats = {}

    cats_id = 1
    for cats in superb_project[type]["object_classes"]:
        category = cats["name"]
        superb_cats[category] = cats_id
        category_info = {"id": cats_id, "name": category, "supercategory": category}
        self.add_categories(
            [Category.from_dict({**category_info, "category_id": cats_id}, task=self.task)]
        )

        cats_id += 1
    return superb_cats


def _superbai_det_sequence(self, superb_project, superb_metas):
    superb_cats = _get_superb_det_categories(self, superb_project, type="object_tracking")

    image_id = 1
    annotation_id = 1
    total_length = 0

    for meta_path in superb_metas:
        meta = io.load_json(meta_path)
        anno_data = io.load_json(self.superb_label_dir / meta["label_path"][0])
        frames = []
        for anns in anno_data["objects"]:
            for frame in anns["frames"]:
                frames.append(frame["num"])
        total_length += len(set(frames))

    logging.info(f"Importing superb ai dataset, Total Images: {total_length}")
    pgbar = tqdm.tqdm(total=total_length, desc="Importing SuperbAI dataset")

    for meta_path in superb_metas:
        labels = defaultdict(list)
        meta = io.load_json(meta_path)
        anno_data = io.load_json(self.superb_label_dir / meta["label_path"][0])
        for anns in anno_data["objects"]:
            class_name = anns["class_name"]
            for frame in anns["frames"]:
                labels[frame["num"]].append([class_name, frame["annotation"]["coord"]])

        for image_num, annos in labels.items():
            filename = meta["frames"][int(image_num)]
            subfilename = f"{meta['data_key'].lstrip('/')}/{filename}"
            image_path = self.superb_image_dir / subfilename
            if not image_path.exists():
                raise FileNotFoundError(f"{image_path} does not exist.")

            self.add_images(
                [
                    Image.from_dict(
                        {
                            "width": meta["image_info"]["width"],
                            "height": meta["image_info"]["height"],
                            "image_id": image_id,
                            "file_name": subfilename,
                        }
                    )
                ]
            )
            io.copy_file(image_path, self.raw_image_dir / subfilename, create_directory=True)
            for anno in annos:
                class_name = anno[0]
                coord = anno[1]
                self.add_annotations(
                    [
                        Annotation.from_dict(
                            {
                                "annotation_id": annotation_id,
                                "image_id": image_id,
                                "bbox": [coord["x"], coord["y"], coord["width"], coord["height"]],
                                "category_id": superb_cats[class_name],
                            },
                            task=self.task,
                        )
                    ]
                )
                annotation_id += 1
            image_id += 1
            pgbar.update(1)
    pgbar.close()


def _superbai_det_image(self, superb_project, superb_metas):
    superb_cats = _get_superb_det_categories(self, superb_project, type="object_detection")
    image_id = 1
    annotation_id = 1

    total_length = len(superb_metas)
    pgbar = tqdm.tqdm(total=total_length, desc="Importing SuperbAI dataset")
    logging.info(f"Importing superb ai dataset, Total Length: {total_length}")

    for meta_path in superb_metas:
        meta = io.load_json(meta_path)
        anno_data = io.load_json(self.superb_label_dir / meta["label_path"][0])
        file_name = str(meta["data_key"]).lstrip("/")
        image_path = self.superb_image_dir / file_name

        if not image_path.exists():
            raise FileNotFoundError(f"{image_path} does not exist.")

        self.add_images(
            [
                Image.from_dict(
                    {
                        "image_id": image_id,
                        "file_name": file_name,
                        "width": meta["image_info"]["width"],
                        "height": meta["image_info"]["height"],
                    }
                )
            ]
        )
        io.copy_file(image_path, self.raw_image_dir / file_name, create_directory=True)

        for label_info in anno_data["objects"]:
            class_name = label_info["class_name"]
            coord = label_info["annotation"]["coord"]
            self.add_annotations(
                [
                    Annotation.from_dict(
                        {
                            "image_id": image_id,
                            "annotation_id": annotation_id,
                            "bbox": [coord["x"], coord["y"], coord["width"], coord["height"]],
                            "area": 0,
                            "iscrowd": 0,
                            "category_id": superb_cats[class_name],
                        },
                        task=self.task,
                    )
                ]
            )
            annotation_id += 1
        image_id += 1
        pgbar.update(1)
    pgbar.close()


def _import_superb_ai_detection(self):
    superb_project = io.load_json(self.superb_label_dir / "project.json")
    superb_metas = list(Path(self.superb_label_dir).glob("meta/**/*json"))

    if superb_project["data_type"] == "image":
        _superbai_det_image(self, superb_project, superb_metas)
    elif superb_project["data_type"] == "image sequence":
        _superbai_det_sequence(self, superb_project, superb_metas)


def import_superb_ai(self, superb_image_dir, superb_label_dir):
    """
    Import coco dataset

    Args:
        superb_image_dir (list[str]): List of superb ai image files root directory
        superb_label_dir (list[str]): List of superb ai meta files and project file root directory
    """
    _import = _import_superb_ai_detection

    self.superb_image_dir = Path(superb_image_dir)
    self.superb_label_dir = Path(superb_label_dir)

    _import(self)

    # TODO: add unlabeled set
    io.save_json([], self.unlabeled_set_file, create_directory=True)