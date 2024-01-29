# Copyright 2020 MONAI Consortium
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging
from typing import TYPE_CHECKING, Callable, Optional, Union

import numpy as np

from monai.data import PNGSaver
from monai.utils import GridSampleMode, GridSamplePadMode, InterpolateMode, exact_version, optional_import
# Copyright 2020 MONAI Consortium
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from typing import Dict, Optional, Union

import numpy as np
import torch

from monai.data.nifti_writer import write_nifti
from monai.data.utils import create_file_basename
from monai.utils import GridSampleMode, GridSamplePadMode


class NiftiSaver:
    """
    Save the data as NIfTI file, it can support single data content or a batch of data.
    Typically, the data can be segmentation predictions, call `save` for single data
    or call `save_batch` to save a batch of data together. If no meta data provided,
    use index from 0 as the filename prefix.
    """

    def __init__(
        self,
        output_dir: str = "./",
        output_postfix: str = "seg",
        output_ext: str = ".nii.gz",
        resample: bool = True,
        mode: Union[GridSampleMode, str] = GridSampleMode.BILINEAR,
        padding_mode: Union[GridSamplePadMode, str] = GridSamplePadMode.BORDER,
        align_corners: bool = False,
        dtype: Optional[np.dtype] = np.float64,
    ) -> None:
        """
        Args:
            output_dir: output image directory.
            output_postfix: a string appended to all output file names.
            output_ext: output file extension name.
            resample: whether to resample before saving the data array.
            mode: {``"bilinear"``, ``"nearest"``}
                This option is used when ``resample = True``.
                Interpolation mode to calculate output values. Defaults to ``"bilinear"``.
                See also: https://pytorch.org/docs/stable/nn.functional.html#grid-sample
            padding_mode: {``"zeros"``, ``"border"``, ``"reflection"``}
                This option is used when ``resample = True``.
                Padding mode for outside grid values. Defaults to ``"border"``.
                See also: https://pytorch.org/docs/stable/nn.functional.html#grid-sample
            align_corners: Geometrically, we consider the pixels of the input as squares rather than points.
                See also: https://pytorch.org/docs/stable/nn.functional.html#grid-sample
            dtype: data type for resampling computation. Defaults to ``np.float64`` for best precision.
                If None, use the data type of input data. To be compatible with other modules,
                the output data type is always ``np.float32``.
        """
        self.output_dir = output_dir
        self.output_postfix = output_postfix
        self.output_ext = output_ext
        self.resample = resample
        self.mode: GridSampleMode = GridSampleMode(mode)
        self.padding_mode: GridSamplePadMode = GridSamplePadMode(padding_mode)
        self.align_corners = align_corners
        self.dtype = dtype
        self._data_index = 0

    def save(self, data: Union[torch.Tensor, np.ndarray], meta_data: Optional[Dict] = None) -> None:
        """
        Save data into a Nifti file.
        The meta_data could optionally have the following keys:

            - ``'filename_or_obj'`` -- for output file name creation, corresponding to filename or object.
            - ``'original_affine'`` -- for data orientation handling, defaulting to an identity matrix.
            - ``'affine'`` -- for data output affine, defaulting to an identity matrix.
            - ``'spatial_shape'`` -- for data output shape.

        When meta_data is specified, the saver will try to resample batch data from the space
        defined by "affine" to the space defined by "original_affine".

        If meta_data is None, use the default index (starting from 0) as the filename.

        Args:
            data: target data content that to be saved as a NIfTI format file.
                Assuming the data shape starts with a channel dimension and followed by spatial dimensions.
            meta_data: the meta data information corresponding to the data.

        See Also
            :py:meth:`monai.data.nifti_writer.write_nifti`
        """
        # filename = meta_data["filename_or_obj"] if meta_data else str(self._data_index)
        self._data_index += 1
        original_affine = meta_data.get("original_affine", None) if meta_data else None
        affine = meta_data.get("affine", None) if meta_data else None
        spatial_shape = meta_data.get("spatial_shape", None) if meta_data else None

        if torch.is_tensor(data):
            data = data.detach().cpu().numpy()

        # filename = create_file_basename(self.output_postfix, filename, self.output_dir)
        # filename = f"{filename}{self.output_ext}"
        filename=meta_data["filename_or_obj"].replace("image","mask")
        # change data shape to be (channel, h, w, d)
        while len(data.shape) < 4:
            data = np.expand_dims(data, -1)
        # change data to "channel last" format and write to nifti format file
        data = np.moveaxis(data, 0, -1)
        write_nifti(
            data,
            file_name=filename.replace("_reo/","_seg/"),
            affine=affine,
            target_affine=original_affine,
            resample=self.resample,
            output_spatial_shape=spatial_shape,
            mode=self.mode,
            padding_mode=self.padding_mode,
            align_corners=self.align_corners,
            dtype=self.dtype,
        )

    def save_batch(self, batch_data: Union[torch.Tensor, np.ndarray], meta_data: Optional[Dict] = None) -> None:
        """
        Save a batch of data into Nifti format files.

        Spatially it supports up to three dimensions, that is, H, HW, HWD for
        1D, 2D, 3D respectively (with resampling supports for 2D and 3D only).

        When saving multiple time steps or multiple channels `batch_data`,
        time and/or modality axes should be appended after the batch dimensions.
        For example, the shape of a batch of 2D eight-class
        segmentation probabilities to be saved could be `(batch, 8, 64, 64)`;
        in this case each item in the batch will be saved as (64, 64, 1, 8)
        NIfTI file (the third dimension is reserved as a spatial dimension).

        Args:
            batch_data: target batch data content that save into NIfTI format.
            meta_data: every key-value in the meta_data is corresponding to a batch of data.
        """
        for i, data in enumerate(batch_data):  # save a batch of files
            self.save(data, {k: meta_data[k][i] for k in meta_data} if meta_data else None)

Events, _ = optional_import("ignite.engine", "0.4.2", exact_version, "Events")
if TYPE_CHECKING:
    from ignite.engine import Engine
else:
    Engine, _ = optional_import("ignite.engine", "0.4.2", exact_version, "Engine")


class SegmentationSaver:
    """
    Event handler triggered on completing every iteration to save the segmentation predictions into files.
    """

    def __init__(
        self,
        output_dir: str = "./",
        output_postfix: str = "seg",
        output_ext: str = ".nii.gz",
        resample: bool = True,
        mode: Union[GridSampleMode, InterpolateMode, str] = "nearest",
        padding_mode: Union[GridSamplePadMode, str] = GridSamplePadMode.BORDER,
        scale: Optional[int] = None,
        dtype: Optional[np.dtype] = None,
        batch_transform: Callable = lambda x: x,
        output_transform: Callable = lambda x: x,
        name: Optional[str] = None,
    ) -> None:
        """
        Args:
            output_dir: output image directory.
            output_postfix: a string appended to all output file names.
            output_ext: output file extension name.
            resample: whether to resample before saving the data array.
            mode: This option is used when ``resample = True``. Defaults to ``"nearest"``.

                - NIfTI files {``"bilinear"``, ``"nearest"``}
                    Interpolation mode to calculate output values.
                    See also: https://pytorch.org/docs/stable/nn.functional.html#grid-sample
                - PNG files {``"nearest"``, ``"linear"``, ``"bilinear"``, ``"bicubic"``, ``"trilinear"``, ``"area"``}
                    The interpolation mode.
                    See also: https://pytorch.org/docs/stable/nn.functional.html#interpolate

            padding_mode: This option is used when ``resample = True``. Defaults to ``"border"``.

                - NIfTI files {``"zeros"``, ``"border"``, ``"reflection"``}
                    Padding mode for outside grid values.
                    See also: https://pytorch.org/docs/stable/nn.functional.html#grid-sample
                - PNG files
                    This option is ignored.

            scale: {``255``, ``65535``} postprocess data by clipping to [0, 1] and scaling
                [0, 255] (uint8) or [0, 65535] (uint16). Default is None to disable scaling.
                It's used for PNG format only.
            dtype: convert the image data to save to this data type.
                If None, keep the original type of data. It's used for Nifti format only.
            batch_transform: a callable that is used to transform the
                ignite.engine.batch into expected format to extract the meta_data dictionary.
            output_transform: a callable that is used to transform the
                ignite.engine.output into the form expected image data.
                The first dimension of this transform's output will be treated as the
                batch dimension. Each item in the batch will be saved individually.
            name: identifier of logging.logger to use, defaulting to `engine.logger`.

        """
        self.saver: Union[NiftiSaver, PNGSaver]
        if output_ext in (".nii.gz", ".nii"):
            self.saver = NiftiSaver(
                output_dir=output_dir,
                output_postfix=output_postfix,
                output_ext=output_ext,
                resample=resample,
                mode=GridSampleMode(mode),
                padding_mode=padding_mode,
                dtype=dtype,
            )
        elif output_ext == ".png":
            self.saver = PNGSaver(
                output_dir=output_dir,
                output_postfix=output_postfix,
                output_ext=output_ext,
                resample=resample,
                mode=InterpolateMode(mode),
                scale=scale,
            )
        self.batch_transform = batch_transform
        self.output_transform = output_transform

        self.logger = logging.getLogger(name)
        self._name = name

    def attach(self, engine: Engine) -> None:
        """
        Args:
            engine: Ignite Engine, it can be a trainer, validator or evaluator.
        """
        if self._name is None:
            self.logger = engine.logger
        if not engine.has_event_handler(self, Events.ITERATION_COMPLETED):
            engine.add_event_handler(Events.ITERATION_COMPLETED, self)

    def __call__(self, engine: Engine) -> None:
        """
        This method assumes self.batch_transform will extract metadata from the input batch.
        Output file datatype is determined from ``engine.state.output.dtype``.

        Args:
            engine: Ignite Engine, it can be a trainer, validator or evaluator.
        """
        meta_data = self.batch_transform(engine.state.batch)
        engine_output = self.output_transform(engine.state.output)
        self.saver.save_batch(engine_output, meta_data)
        self.logger.info("saved all the model outputs into files.")
