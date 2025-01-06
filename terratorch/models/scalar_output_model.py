# Copyright contributors to the Terratorch project

import torch
from segmentation_models_pytorch.base import SegmentationModel
from torch import nn
import torchvision.transforms as transforms
from terratorch.models.heads import ClassificationHead
from terratorch.models.model import AuxiliaryHeadWithDecoderWithoutInstantiatedHead, Model, ModelOutput
from terratorch.models.utils import pad_images

def freeze_module(module: nn.Module):
    for param in module.parameters():
        param.requires_grad_(False)


class ScalarOutputModel(Model, SegmentationModel):
    """Model that encapsulates encoder and decoder and heads for a scalar output
    Expects decoder to have a "forward_features" method, an embed_dims property
    and optionally a "prepare_features_for_image_model" method.
    """

    def __init__(
        self,
        task: str,
        encoder: nn.Module,
        decoder: nn.Module,
        head_kwargs: dict,
        patch_size:int = None,
        decoder_includes_head: bool = False,
        auxiliary_heads: list[AuxiliaryHeadWithDecoderWithoutInstantiatedHead] | None = None,
        neck: nn.Module | None = None,
    ) -> None:
        """Constructor

        Args:
            task (str): Task to be performed. Must be "classification".
            encoder (nn.Module): Encoder to be used
            decoder (nn.Module): Decoder to be used
            head_kwargs (dict): Arguments to be passed at instantiation of the head.
            decoder_includes_head (bool): Whether the decoder already incldes a head. If true, a head will not be added. Defaults to False.
            auxiliary_heads (list[AuxiliaryHeadWithDecoderWithoutInstantiatedHead] | None, optional): List of
                AuxiliaryHeads with heads to be instantiated. Defaults to None.
            neck (nn.Module | None): Module applied between backbone and decoder.
                Defaults to None, which applies the identity.
        """
        super().__init__()
        self.task = task
        self.encoder = encoder
        self.decoder = decoder
        self.head = (
            self._get_head(task, decoder.out_channels, head_kwargs) if not decoder_includes_head else nn.Identity()
        )

        if auxiliary_heads is not None:
            aux_heads = {}
            for aux_head_to_be_instantiated in auxiliary_heads:
                aux_head: nn.Module = self._get_head(
                    task, aux_head_to_be_instantiated.decoder.out_channels, head_kwargs
                ) if not aux_head_to_be_instantiated.decoder_includes_head else nn.Identity()
                aux_head = nn.Sequential(aux_head_to_be_instantiated.decoder, aux_head)
                aux_heads[aux_head_to_be_instantiated.name] = aux_head
        else:
            aux_heads = {}
        self.aux_heads = nn.ModuleDict(aux_heads)

        self.neck = neck
        self.patch_size = patch_size

    def freeze_encoder(self):
        freeze_module(self.encoder)

    def freeze_decoder(self):
        freeze_module(self.decoder)
        freeze_module(self.head)

    def check_input_shape(self, x: torch.Tensor) -> torch.Tensor:  # noqa: ARG002

        if self.patch_size:
            x_shape = x.shape[2:]
            if all([i//self.patch_size==0 for i in x_shape]):
               return x
            else:
               x = pad_images(x, self.patch_size, "constant") 
               return x
        else:
            # If patch size is not provided, the user should guarantee the
            # dataset is properly configured to work with the model being used. 
            return x

    def _crop_image_when_necessary(self, x:torch.Tensor, size:tuple) -> torch.Tensor:

        return transforms.CenterCrop(size)(x)

    def forward(self, x: torch.Tensor, **kwargs) -> ModelOutput:
        """Sequentially pass `x` through model`s encoder, decoder and heads"""

        x = self.check_input_shape(x)
        features = self.encoder(x, **kwargs)

        # Collecting information about the size of the input tensor in order to 
        # use it to possibly crop the image when necessary. 
        input_size = x.shape[-2:]

        ## only for backwards compatibility with pre-neck times.
        if self.neck:
            prepare = self.neck
        else:
            # for backwards compatibility, if this is defined in the encoder, use it
            prepare = getattr(self.encoder, "prepare_features_for_image_model", lambda x: x)

        features = prepare(features)

        decoder_output = self.decoder([f.clone() for f in features])
        decoder_output = self._crop_image_when_necessary(decoder_output, input_size)
        mask = self.head(decoder_output)

        aux_outputs = {}
        for name, decoder in self.aux_heads.items():
            aux_output = decoder([f.clone() for f in features])
            aux_outputs[name] = aux_output

        return ModelOutput(output=mask, auxiliary_heads=aux_outputs)

    def _get_head(self, task: str, input_embed_dim: int, head_kwargs: dict):
        if task == "classification":
            if "num_classes" not in head_kwargs:
                msg = "num_classes must be defined for classification task"
                raise Exception(msg)
            return ClassificationHead(input_embed_dim, **head_kwargs)
        msg = "Task must be classification."
        raise Exception(msg)
