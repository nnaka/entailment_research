#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Usage:
    $ spark-submit --deploy-mode client _.py
"""

from argparse import ArgumentParser
import csv
from enum import Enum
import functools
import os
import sys
from typing import Dict, Generator, List, Optional, Tuple, Union


# Must be called before the import of transformers etc to properly set the .cache dir
def setup_env(path: str) -> None:
    """Modifying where the .cache directory is getting stored"""
    os.environ["HF_HOME"] = path
    os.environ["TORCH_HOME"] = path
    os.environ["TRANSFORMERS_CACHE"] = path
    print(
        f"Environment variables set TORCH_HOME = {os.environ['TORCH_HOME']}; HF_HOME={os.environ['HF_HOME']}; TRANSFORMERS_CACHE={os.environ['TRANSFORMERS_CACHE']}"
    )


setup_env("/scratch/nn1331/entailment/.cache")

from datasets import Dataset, load_dataset
import evaluate
import nltk
from nltk.tokenize import sent_tokenize
import numpy as np
import torch
from transformers import (
    AutoModelForSequenceClassification,
    AutoModelForSeq2SeqLM,
    AutoTokenizer,
    DataCollatorWithPadding,
    pipeline,
    Pipeline,
    TrainingArguments,
    Trainer,
)

NUM_SENTENCES_IN_PRIOR: int = 5


class EntailmentCategory(Enum):
    CONTRADICTION = 0
    NEUTRAL = 1
    ENTAILMENT = 2


def create_preprocess_function(tokenizer):
    # TODO: review what's the best way to include premise and the hypothesis
    def preprocess_function(examples):
        print(examples)
        entries_to_remove: List[str] = [
            "promptID",
            "pairID",
            "premise_binary_parse",
            "premise_parse",
            "hypothesis_binary_parse",
            "hypothesis_parse",
            "genre",
        ]
        for entry in entries_to_remove:
            examples.pop(entry, None)

        print(examples["premise"])
        # Truncate context
        examples["premise"] = [
            tokenizer(example, truncation=True) for example in examples["premise"]
        ]
        print(examples["premise"])
        examples["hypothesis"] = [
            tokenizer(example, truncation=True) for example in examples["hypothesis"]
        ]
        return examples

    return preprocess_function


def compute_metrics(eval_pred):
    predictions, labels = eval_pred
    predictions = np.argmax(predictions, axis=1)
    return accuracy.compute(predictions=predictions, references=labels)


def main(is_full: bool, is_final: bool, output_path: str = None) -> None:
    """Main routine"""
    run_zero_shot_nli(output_path)


def run_zero_shot_nli(output: str = None) -> None:
    # Run smaller T5 model for interactive mode purposes
    """
    tokenizer = AutoTokenizer.from_pretrained("t5-small")
    nli_model = AutoModelForSeq2SeqLM.from_pretrained(
        "t5-small",
        device_map="auto",
        offload_folder="offload_folder",
        torch_dtype="auto",
        offload_state_dict=True,
    )
    """

    """
    """
    tokenizer = AutoTokenizer.from_pretrained("google/t5_xxl_true_nli_mixture")
    nli_model = AutoModelForSeq2SeqLM.from_pretrained(
        "google/t5_xxl_true_nli_mixture",
        device_map="auto",
        offload_folder="offload_folder",
        torch_dtype="auto",
        offload_state_dict=True,
    )

    nli_model.eval()  # disable dropout for evaluation
    assert torch.cuda.is_available()
    # Move model to GPU (currently errors out due to model being both on CPU / GPU)
    # nli_model.cuda()  # run on gpu

    # Test
    premise: str = "This model is a heavily optimized version of BERT."
    hypothesis: str = "This model is not very optimized."
    model_input: List[int] = tokenizer.encode(
        f"premise: {premise} hypothesis: {hypothesis}", return_tensors="pt"
    ).cuda()

    print(f"TEST 1:")
    print(
        tokenizer.decode(nli_model.generate(model_input)[0], skip_special_tokens=True)
    )
    # print(nli_model.generate(model_input)[0])  # 0: not entailment

    hypothesis = "Roberta is based on BERT."
    model_input = tokenizer.encode(
        f"premise: {premise} hypothesis: {hypothesis}", return_tensors="pt"
    ).cuda()

    print(f"TEST 2:")
    print(
        tokenizer.decode(nli_model.generate(model_input)[0], skip_special_tokens=True)
    )
    # print(nli_model.predict(model_input).argmax())  # 1: entailment

    # Experiment
    # entailment classification for summarized groups of n sentences of data
    # classify_summarized_text(nli_model, tokenizer, output_path)

    # Dataset source: https://huggingface.co/datasets/openwebtext
    # dataset: Dataset = load_dataset("openwebtext")

    # TODO (nnaka): follow up tests of Pile data (https://arxiv.org/pdf/2101.00027.pdf) subsets
    # Dataset source: https://huggingface.co/datasets/monology/pile-uncopyrighted
    # https://huggingface.co/datasets/EleutherAI/pile doesn't work due to
    # https://huggingface.co/datasets/EleutherAI/pile/discussions/15
    # dataset: Dataset = load_dataset("monology/pile-uncopyrighted", split="test[:50%]")
    # DATASET_NAME: str = "suolyer/pile_books3"
    # dataset: Dataset = load_dataset(DATASET_NAME, split="test")["text"]
    # dataset: Dataset = load_dataset("suolyer/pile_youtubesubtitles", split="test")[
    #     "text"
    # ]
    # dataset: Dataset = load_dataset("suolyer/pile_freelaw", split="test")["text"]
    # dataset: Dataset = load_dataset("suolyer/pile_wikipedia", split="test")["text"]
    # dataset: Dataset = load_dataset("suolyer/pile_arxiv", split="test")["text"]
    # dataset: Dataset = load_dataset("suolyer/pile_arxiv", split="test")["text"]
    # DATASET_NAME: str = "multi_news"
    # dataset: Dataset = load_dataset(DATASET_NAME, split="test")["document"]
    DATASET_NAME: str = "yelp_review_full"
    dataset: Dataset = load_dataset(DATASET_NAME, split="test")["text"]
    # DATASET_NAME: str = "reuters21578"
    # dataset: Dataset = load_dataset(DATASET_NAME, "ModHayes", split="test")["text"]
    # DATASET_NAME: str = "yahoo_answers_topics"
    # dataset: Dataset = load_dataset(DATASET_NAME, split="test")["best_answer"]

    DEFUALT_OUTPUT_CSV_FILE_PATH: str = (
        f"/scratch/nn1331/entailment/data-{DATASET_NAME.split('/')[-1]}.csv"
    )
    output_path: str = DEFUALT_OUTPUT_CSV_FILE_PATH if output is None else output

    # import pdb; pdb.set_trace()
    classify_dataset_text(nli_model, tokenizer, dataset, output_path)


def get_premise_and_hypothesis(
    document: str, n: int
) -> Generator[Tuple[str, str], None, None]:
    """premise is last n sentences before hypothesis"""
    sentences: List[str] = sent_tokenize(document)
    premise: str = ""
    hypothesis: str = ""
    for i, sentence in enumerate(sentences):
        if i >= n + 1:
            premise = "".join(sentences[i - n : i])
            hypothesis = sentences[i]
            yield premise, hypothesis


def get_csv_writer(file_path: str = None):
    """Either write to file path or to stdout"""
    if file_path is not None:
        csv_file = open(file_path, "w", newline="")
        return csv.writer(csv_file), csv_file
    else:
        return csv.writer(sys.stdout), csv_file


def get_n_sentences(s: str, n: int) -> Generator[str, None, None]:
    """Return groups of n sentences of s"""
    sentences: List[str] = sent_tokenize(s)
    premise: str = ""
    hypothesis: str = ""
    for i in range(0, len(sentences), n):
        yield " ".join(sentences[i : i + n])


def classify_summarized_text(
    model: AutoModelForSeq2SeqLM, tokenizer: AutoTokenizer, file_path: str = None
) -> None:
    """Classification forcing entailment via summarization of premise as hypothesis"""
    # Dataset source: https://huggingface.co/datasets/openwebtext
    dataset: Dataset = load_dataset("openwebtext", split="train")

    # Get entailment examples
    results: Dict[EntailmentCategory, List[str]] = {
        EntailmentCategory.CONTRADICTION: [],
        EntailmentCategory.ENTAILMENT: [],
        EntailmentCategory.NEUTRAL: [],
    }

    print(f"{len(dataset)} training examples")

    # NLTK package for splitting sentences
    nltk.download("punkt")

    # Write results in csv
    csv_writer = get_csv_writer(file_path)

    id2label: Dict[int, EntailmentCategory] = {i.value: i for i in EntailmentCategory}

    premise: str = ""
    hypothesis: str = ""

    # Summarization model
    classifier: Pipeline = pipeline("summarization")

    for data in dataset:
        # Split into predicate + hypothesis and try every n-previous + sentence window in document
        # Make sure the tokenization is within the 512-token limit
        for i, premise in enumerate(get_n_sentences(data["text"], 150)):
            # Summarize premise
            try:
                print(f"HERE: {classifier(premise)}")
                print(f"HERE2: {classifier(premise)[0]['summary_text']}")

                hypothesis = classifier(premise)[0]["summary_text"]
            except IndexError as e:
                print(f"ERROR: {e}")
                continue

            tokens: torch.Tensor = tokenizer.encode(
                f"premise: {premise} hypothesis: {hypothesis}", return_tensors="pt"
            ).cuda()

            print(
                f"PREMISE: {premise}; HYPOTHESIS: {hypothesis}; TOKENS: {tokens}; size: {tokens.size()}"
            )

            if tokens.size(dim=0) > 512:
                # raise ValueError("Input exceeds the 512-token limit.")
                print("Input exceeds the 512-token limit.")
            else:
                label: str = tokenizer.decode(
                    model.generate(tokens)[0], skip_special_tokens=True
                )

                # deprecated
                """
                label: EntailmentCategory = id2label[
                    roberta.predict("mnli", tokens).argmax().item()
                ]
                results[label].append(f'{data["text"]}')
                """
                print(f"Writing result #{i} to csv at path {file_path}")
                csv_writer.writerow([label, premise, hypothesis])


def classify_dataset_text(
    model: AutoModelForSeq2SeqLM,
    tokenizer: AutoTokenizer,
    dataset: Dataset,
    file_path: str = None,
) -> None:
    """Classification (i.e. pair input)"""
    # Get entailment examples
    results: Dict[str, List[str]] = {
        EntailmentCategory.CONTRADICTION.name: [],
        EntailmentCategory.ENTAILMENT.name: [],
        EntailmentCategory.NEUTRAL.name: [],
    }

    print(f"{len(dataset)} examples")

    # NLTK package for splitting sentences
    nltk.download("punkt")

    # Write results in csv
    csv_writer, csv_file = get_csv_writer(file_path)

    premise: str = ""
    hypothesis: str = ""

    for data in dataset:
        # Split into predicate + hypothesis and try every n-previous + sentence window in document
        # Make sure the tokenization is within the 512-token limit
        for i, (premise, hypothesis) in enumerate(
            get_premise_and_hypothesis(data, NUM_SENTENCES_IN_PRIOR)
        ):
            # Hypotheses should be somewhat substantial
            if len(hypothesis.split()) < 5:
                print(
                    f"Skipping iteration {i} for PREMISE: {premise}; HYPOTHESIS: {hypothesis}; since hypothesis is too short"
                )
                continue
            tokens: torch.Tensor = tokenizer.encode(
                f"premise: {premise} hypothesis: {hypothesis}", return_tensors="pt"
            ).cuda()

            print(
                f"PREMISE: {premise}; HYPOTHESIS: {hypothesis}; TOKENS: {tokens}; size: {tokens.size()}"
            )

            if tokens.size(dim=0) > 512:
                # raise ValueError("Input exceeds the 512-token limit.")
                print("Input exceeds the 512-token limit.")
            else:
                label: str = tokenizer.decode(
                    model.generate(tokens)[0], skip_special_tokens=True
                )

                print(f"Writing result #{i} to csv at path {file_path}")
                csv_writer.writerow([label, premise, hypothesis])
                csv_file.flush()


if __name__ == "__main__":
    parser: ArgumentParser = ArgumentParser()
    parser.add_argument(
        "--full", dest="is_full", action="store_true", help="Run on full dataset"
    )
    parser.add_argument(
        "--final",
        dest="is_final",
        action="store_true",
        help="Run on final datasets, train/test",
    )
    parser.add_argument(
        "--out",
        dest="output",
        type=str,
        help="Output CSV file path",
    )

    args = parser.parse_args()
    print(f"Using args: {args}")

    # Create the spark session object
    # spark = SparkSession.builder.appName("final_project").getOrCreate()

    # Call our main routine
    # main(spark, args.is_full, args.is_final)
    main(args.is_full, args.is_final, args.output)
