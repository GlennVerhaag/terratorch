from collections.abc import Sequence
from pathlib import Path

import albumentations as A
import h5py
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import torch
from matplotlib import colormaps
from matplotlib.figure import Figure
from matplotlib.colors import Normalize

from terratorch.datasets.utils import default_transform, validate_bands
from torchgeo.datasets import NonGeoDataset


class Landslide4SenseNonGeo(NonGeoDataset):
    """NonGeo dataset implementation for [Landslide4Sense](https://huggingface.co/datasets/ibm-nasa-geospatial/Landslide4sense)."""
    all_band_names = (
        "COASTAL AEROSOL",
        "BLUE",
        "GREEN",
        "RED",
        "RED_EDGE_1",
        "RED_EDGE_2",
        "RED_EDGE_3",
        "NIR_BROAD",
        "WATER_VAPOR",
        "CIRRUS",
        "SWIR_1",
        "SWIR_2",
        "SLOPE",
        "DEM",
    )

    rgb_bands = ("RED", "GREEN", "BLUE")
    BAND_SETS = {"all": all_band_names, "rgb": rgb_bands}

    splits = {"train": "train", "val": "validation", "test": "test"}


    def __init__(
        self,
        data_root: str,
        split: str = "train",
        bands: Sequence[str] = BAND_SETS["all"],
        transform: A.Compose | None = None,
    ) -> None:
        """Initialize the Landslide4Sense dataset.

        Args:
            data_root (str): Path to the data root directory.
            split (str): One of 'train', 'validation', or 'test'.
            bands (Sequence[str]): Bands to be used. Defaults to all bands.
            transform (A.Compose | None): Albumentations transform to be applied.
                Defaults to None, which applies default_transform().
        """
        super().__init__()

        if split not in self.splits:
            msg = f"Incorrect split '{split}', please choose one of {list(self.splits.keys())}."
            raise ValueError(msg)
        split_name = self.splits[split]
        self.split = split

        validate_bands(bands, self.all_band_names)
        self.bands = bands
        self.band_indices = [self.all_band_names.index(b) for b in bands]

        self.data_directory = Path(data_root)

        images_dir = self.data_directory / "images" / split_name
        annotations_dir = self.data_directory / "annotations" / split_name

        self.image_files = sorted(images_dir.glob("image_*.h5"))
        self.mask_files = sorted(annotations_dir.glob("mask_*.h5"))

        self.transform = transform if transform else default_transform

    def __len__(self) -> int:
        return len(self.image_files)

    def __getitem__(self, index: int) -> dict[str, torch.Tensor]:
        image_file = self.image_files[index]
        mask_file = self.mask_files[index]

        with h5py.File(image_file, "r") as h5file:
            image = np.array(h5file["img"])[..., self.band_indices]

        with h5py.File(mask_file, "r") as h5file:
            mask = np.array(h5file["mask"])

        output = {"image": image.astype(np.float32), "mask": mask}

        if self.transform:
            output = self.transform(**output)
        output["mask"] = output["mask"].long()

        return output

    def plot(self, sample: dict[str, torch.Tensor], suptitle: str | None = None, save_path: str | None = None) -> Figure:
        """ Plot a sample from the dataset
        
        Args:
            sample (dict[str, Tensor]): a sample returned by :meth:`__getitem__`
            suptitle (str|None): optional string to be used as the figure's suptitle
            save_path (str|None): optional string defining the file path to save the generated figure

        Returns:
            A matplotlib Figure with the rendered sample
        """
        rgb_indices = [self.bands.index(band) for band in self.rgb_bands if band in self.bands]

        if len(rgb_indices) != 3:
            msg = "Dataset doesn't contain some of the RGB bands"
            raise ValueError(msg)

        image = sample["image"]
        mask = sample["mask"].numpy()
        if torch.is_tensor(image):
            image = image.permute(1, 2, 0).numpy()

        rgb_image = image[:, :, rgb_indices]

        rgb_image = (rgb_image - rgb_image.min(axis=(0, 1))) * (1 / rgb_image.max(axis=(0, 1)))
        rgb_image = np.clip(rgb_image, 0, 1)

        num_classes = len(np.unique(mask))
        cmap = colormaps["jet"]
        norm = Normalize(vmin=0, vmax=num_classes - 1)

        num_images = 4 if "prediction" in sample else 3
        fig, ax = plt.subplots(1, num_images, figsize=(num_images * 4, 4.5), tight_layout=True)

        ax[0].imshow(rgb_image)
        ax[0].set_title("Image")
        ax[0].axis("off")

        ax[1].imshow(mask, cmap=cmap, norm=norm)
        ax[1].set_title("Ground Truth Mask")
        ax[1].axis("off")

        ax[2].imshow(rgb_image)
        ax[2].imshow(mask, cmap=cmap, alpha=0.3, norm=norm)
        ax[2].set_title("GT Mask on Image")
        ax[2].axis("off")
        
        if "prediction" in sample:
            prediction = sample["prediction"]
            ax[3].imshow(prediction, cmap=cmap, norm=norm)
            ax[3].set_title("Predicted Mask")
            ax[3].axis("off")

        if sample.get("class_names"):
            class_names = sample["class_names"]
            legend_handles = [
                mpatches.Patch(color=cmap(i), label=class_names[i]) for i in range(num_classes)
            ]
            ax[0].legend(handles=legend_handles, bbox_to_anchor=(1.05, 1), loc="upper left")

        if suptitle is not None:
            plt.suptitle(suptitle)
            
        if save_path is not None:
            fig.savefig(save_path, dpi=500)

        return fig
