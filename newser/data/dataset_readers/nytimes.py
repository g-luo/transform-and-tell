import logging
import os
import random
from datetime import datetime
from typing import Dict

import numpy as np
from allennlp.data.dataset_readers.dataset_reader import DatasetReader
from allennlp.data.fields import ArrayField, MetadataField, TextField
from allennlp.data.instance import Instance
from allennlp.data.token_indexers import SingleIdTokenIndexer, TokenIndexer
from allennlp.data.tokenizers import Tokenizer, WordTokenizer
from overrides import overrides
from PIL import Image
from pymongo import MongoClient
from torchvision.transforms import (CenterCrop, Compose, Normalize, Resize,
                                    ToTensor)

from newser.data.fields import ImageField

logger = logging.getLogger(__name__)  # pylint: disable=invalid-name


@DatasetReader.register('nytimes')
class NYTimesReader(DatasetReader):
    """Read from the New York Times dataset.

    See the repo README for more instruction on how to download the dataset.

    Parameters
    ----------
    tokenizer : ``Tokenizer``
        We use this ``Tokenizer`` for both the premise and the hypothesis.
        See :class:`Tokenizer`.
    token_indexers : ``Dict[str, TokenIndexer]``
        We similarly use this for both the premise and the hypothesis.
        See :class:`TokenIndexer`.
    """

    def __init__(self,
                 tokenizer: Tokenizer,
                 token_indexers: Dict[str, TokenIndexer],
                 image_dir: str,
                 lazy: bool = True) -> None:
        super().__init__(lazy)
        self._tokenizer = tokenizer
        self._token_indexers = token_indexers
        self.client = MongoClient(host='localhost', port=27017)
        self.db = self.client.nytimes
        self.image_dir = image_dir
        self.preprocess = Compose([
            Resize(256), CenterCrop(224), ToTensor(),
            Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])])
        random.seed(1234)

    @overrides
    def _read(self, split: str):
        # split can be either train, valid, or test
        # validation and test sets contain 10K examples each
        if split == 'train':
            start = datetime(1980, 1, 1)
            end = datetime(2018, 7, 1)
        elif split == 'valid':
            start = datetime(2018, 7, 1)
            end = datetime(2018, 10, 1)
        elif split == 'test':
            start = datetime(2018, 10, 1)
            end = datetime(2019, 1, 1)
        else:
            raise ValueError(f'Unknown split: {split}')

        article_cursor = self.db.articles.find({
            'article': {'$ne': ''},  # non-empty article body
            'images': {'$exists': True, '$ne': {}},  # at least one image
            'pub_date': {'$gte': start, '$lt': end},
        })

        for article in article_cursor:
            # Get the top image of the article
            image_name = f"{article['_id']}_0.jpg"
            image_path = os.path.join(self.image_dir, image_name)
            try:
                with Image.open(image_path) as image:
                    if image.size[0] < 256 or image.size[1] < 256:
                        continue
                    image = image.convert('RGB')
            except (FileNotFoundError, OSError):
                continue

            yield self.article_to_instance(article, image)

    def article_to_instance(self, article, image) -> Instance:
        context_text = f"<s> {article['article']} </s>"
        caption_text = f"<s> {article['images']['0']} </s>"

        context_tokens = self._tokenizer.tokenize(context_text)
        caption_tokens = self._tokenizer.tokenize(caption_text)

        fields = {
            'context': TextField(context_tokens, self._token_indexers),
            'image': ImageField(image, self.preprocess),
            'caption': TextField(caption_tokens, self._token_indexers),
        }

        metadata = {'context': context_text,
                    'caption': caption_text}
        fields['metadata'] = MetadataField(metadata)

        return Instance(fields)
