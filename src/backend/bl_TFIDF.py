# @Time : 2021/4/13 13:56
# @Author : Cheng Zhu
# @site : https://gitee.com/lonekey
# @File : tf_idf.py
from config import *
from data_model import *
from gensim.corpora import Dictionary
from gensim.models import TfidfModel
from gensim import similarities
import numpy as np


def compute(report: list, codes: list):
    data_set = report
    data_set.extend(codes)
    dct = Dictionary(data_set)
    corpus = [dct.doc2bow(line) for line in data_set]  # convert corpus to BoW format
    model = TfidfModel(corpus, wlocal=lambda x: 1 + np.log(x))  # fit model
    index_bug_report = similarities.MatrixSimilarity(model[corpus])
    var = index_bug_report[model[corpus[0]]]
    return var[1:]

# report = [["a", "apple", "good"]]
# codes = [["a", "apple"], ["bad"], ["good"]]

# a = compute(report, codes)
# print(a)