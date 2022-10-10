# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: light
#       format_version: '1.5'
#       jupytext_version: 1.14.1
#   kernelspec:
#     display_name: Python 3
#     language: python
#     name: python3
# ---

# + [markdown] _uuid="8f2839f25d086af736a60e9eeb907d3b93b6e0e5" _cell_guid="b1076dfc-b9ad-4769-8c92-a6c4dae69d19"
# # Multiome Quickstart With Sparse Matrices
#
# This notebook is mostly for demonstrating the utility of sparse matrices in this competition. (Especially for the Multiome dataset).
#
# As the Multiome dataset is  very sparse (about 98% of cells are zeros), it benefits greatly from being encoded as sparse matrices. 
#
# This notebook is largely based on [this notebook](https://www.kaggle.com/code/ambrosm/msci-multiome-quickstart) by AmbrosM. It is a nice first attempt at handling Multiome data, and I thought it would informative for kagglers to be able to contrast directly the performances of sparse vs dense representations. 
#
# Mostly, the differences with AmbrosM's notebooks are:
# - We use a representation of the data in sparse CSR format, which let us load all of the training data in memory (using less than 8GB memory instead of the >90GB it would take to represent the data in a dense format)
# - We perform PCA (actually, TruncatedSVD) on the totality of the training data (while AmbrosM's notebook had to work with a subset of 6000 rows and 4000 columns). 
# - We keep 16 components (vs 4 in AmbrosM's notebook)
# - We apply Ridge regression on 50000 rows (vs 6000 in AmbrosM's notebook)
# - Despite using much more data, this notebook should run in a bit more than 10 minutes (vs >1h for AmbrosM's notebook)
#
# The competition data is pre-encoded as sparse matrices in [this dataset](https://www.kaggle.com/datasets/fabiencrom/multimodal-single-cell-as-sparse-matrix) generated by [this notebook](https://www.kaggle.com/code/fabiencrom/multimodal-single-cell-creating-sparse-data/).
#
# Since we will only generate the multiome predictions in this notebook, I am taking the CITEseq predictions from [this notebook](https://www.kaggle.com/code/vuonglam/lgbm-baseline-optuna-drop-constant-cite-task) by VuongLam, which is the public notebook with the best score at the time I am publishing.
#

# + _kg_hide-input=true
import os, gc, pickle
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from colorama import Fore, Back, Style
from matplotlib.ticker import MaxNLocator

from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.model_selection import KFold
from sklearn.preprocessing import StandardScaler, scale
from sklearn.decomposition import PCA, TruncatedSVD
from sklearn.dummy import DummyRegressor
from sklearn.pipeline import make_pipeline, Pipeline
from sklearn.linear_model import Ridge, LinearRegression, Lasso
from sklearn.metrics import mean_squared_error

import scipy
import scipy.sparse


# -

# # The scoring function (from AmbrosM)
#
# This competition has a special metric: For every row, it computes the Pearson correlation between y_true and y_pred, and then all these correlation coefficients are averaged.

def correlation_score(y_true, y_pred):
    """Scores the predictions according to the competition rules. 
    
    It is assumed that the predictions are not constant.
    
    Returns the average of each sample's Pearson correlation coefficient"""
    if type(y_true) == pd.DataFrame: y_true = y_true.values
    if type(y_pred) == pd.DataFrame: y_pred = y_pred.values
    if y_true.shape != y_pred.shape: raise ValueError("Shapes are different.")
    corrsum = 0
    for i in range(len(y_true)):
        corrsum += np.corrcoef(y_true[i], y_pred[i])[1, 0]
    return corrsum / len(y_true)



# # Preprocessing and cross-validation
#
# We first load all of the training input data for Multiome. It should take less than a minute.

# %%time
train_inputs = scipy.sparse.load_npz("../input/multimodal-single-cell-as-sparse-matrix/train_multi_inputs_values.sparse.npz")

# ## PCA / TruncatedSVD
# It is not possible to directly apply PCA to a sparse matrix, because PCA has to first "center" the data, which destroys the sparsity. This is why we apply `TruncatedSVD` instead (which is pretty much "PCA without centering"). It might be better to normalize the data a bit more here, but we will keep it simple.

# %%time
pca = TruncatedSVD(n_components=16, random_state=1)
train_inputs = pca.fit_transform(train_inputs)

# ## Random row selection and conversion of the target data to a dense matrix
#
# Unfortunately, although sklearn's `Ridge` regressor do accept sparse matrices as input, it does not accept sparse matrices as target values. This means we will have to convert the targets to a dense format. Although we could fit in memory both the dense target data and the sparse input data, the Ridge regression process would then lack memory. Therefore, from now on, we will work with a subset of 50 000 rows from the training data.

np.random.seed(42)
all_row_indices = np.arange(train_inputs.shape[0])
np.random.shuffle(all_row_indices)
selected_rows_indices = all_row_indices[:50000]

train_inputs = train_inputs[selected_rows_indices]

# %%time
train_target = scipy.sparse.load_npz("../input/multimodal-single-cell-as-sparse-matrix/train_multi_targets_values.sparse.npz")

train_target = train_target[selected_rows_indices]
train_target = train_target.todense()
gc.collect()

# ## KFold Ridge regression
# `sklearn` complains that we should use array instead of matrices. Unfortunately, the old `scipy` version available on kaggle do not provide sparse arrays; only sparse matrices. So we suppress the warnings.

import warnings
warnings.simplefilter(action='ignore', category=FutureWarning)

# This Kfold ridge regression code is mostly taken from AmbrosM's [notebook](https://www.kaggle.com/code/ambrosm/msci-multiome-quickstart). Note that `sklearn`'s `Ridge` handles sparse matrices transparently. I found [this blog post](https://dziganto.github.io/Sparse-Matrices-For-Efficient-Machine-Learning/) that list the other algorithms of `sklearn` that accept sparse matrices.

# +
# %%time
# Cross-validation

kf = KFold(n_splits=5, shuffle=True, random_state=1)
score_list = []
for fold, (idx_tr, idx_va) in enumerate(kf.split(train_inputs)):
    model = None
    gc.collect()
    X_tr = train_inputs[idx_tr] # creates a copy, https://numpy.org/doc/stable/user/basics.copies.html
    y_tr = train_target[idx_tr]
    del idx_tr

    model = Ridge(copy_X=False)
    model.fit(X_tr, y_tr)
    del X_tr, y_tr
    gc.collect()

    # We validate the model
    X_va = train_inputs[idx_va]
    y_va = train_target[idx_va]
    del idx_va
    y_va_pred = model.predict(X_va)
    mse = mean_squared_error(y_va, y_va_pred)
    corrscore = correlation_score(y_va, y_va_pred)
    del X_va, y_va

    print(f"Fold {fold}: mse = {mse:.5f}, corr =  {corrscore:.3f}")
    score_list.append((mse, corrscore))

# Show overall score
result_df = pd.DataFrame(score_list, columns=['mse', 'corrscore'])
print(f"{Fore.GREEN}{Style.BRIGHT}{train_inputs.shape} Average  mse = {result_df.mse.mean():.5f}; corr = {result_df.corrscore.mean():.3f}{Style.RESET_ALL}")

# -

# # Retraining
#

# We retrain the model and then delete the training data, which is no longer needed
model, score_list, result_df = None, None, None # free the RAM occupied by the old model
gc.collect()
model = Ridge(copy_X=False) # we overwrite the training data
model.fit(train_inputs, train_target)


del train_inputs, train_target # free the RAM
_ = gc.collect()

# # Predicting

# %%time
multi_test_x = scipy.sparse.load_npz("../input/multimodal-single-cell-as-sparse-matrix/test_multi_inputs_values.sparse.npz")
multi_test_x = pca.transform(multi_test_x)
test_pred = model.predict(multi_test_x)
del multi_test_x
gc.collect()

# # Creating submission
#
# We load the cells that will have to appear in submission.

# +
# %%time
# Read the table of rows and columns required for submission
eval_ids = pd.read_parquet("../input/multimodal-single-cell-as-sparse-matrix/evaluation.parquet")

# Convert the string columns to more efficient categorical types
#eval_ids.cell_id = eval_ids.cell_id.apply(lambda s: int(s, base=16))

eval_ids.cell_id = eval_ids.cell_id.astype(pd.CategoricalDtype())
eval_ids.gene_id = eval_ids.gene_id.astype(pd.CategoricalDtype())

# -

# Prepare an empty series which will be filled with predictions
submission = pd.Series(name='target',
                       index=pd.MultiIndex.from_frame(eval_ids), 
                       dtype=np.float32)
submission

# We load the `index`  and `columns` of the original dataframe, as we need them to make the submission.

# +
# %%time
y_columns = np.load("../input/multimodal-single-cell-as-sparse-matrix/train_multi_targets_idxcol.npz",
                   allow_pickle=True)["columns"]

test_index = np.load("../input/multimodal-single-cell-as-sparse-matrix/test_multi_inputs_idxcol.npz",
                    allow_pickle=True)["index"]
# -

# We assign the predicted values to the correct row in the submission file.

# +
cell_dict = dict((k,v) for v,k in enumerate(test_index)) 
assert len(cell_dict)  == len(test_index)

gene_dict = dict((k,v) for v,k in enumerate(y_columns))
assert len(gene_dict) == len(y_columns)

# +
eval_ids_cell_num = eval_ids.cell_id.apply(lambda x:cell_dict.get(x, -1))
eval_ids_gene_num = eval_ids.gene_id.apply(lambda x:gene_dict.get(x, -1))

valid_multi_rows = (eval_ids_gene_num !=-1) & (eval_ids_cell_num!=-1)
# -

submission.iloc[valid_multi_rows] = test_pred[eval_ids_cell_num[valid_multi_rows].to_numpy(),
eval_ids_gene_num[valid_multi_rows].to_numpy()]

del eval_ids_cell_num, eval_ids_gene_num, valid_multi_rows, eval_ids, test_index, y_columns
gc.collect()

submission

# # Merging with CITEseq predictions
#
# We use the CITEseq predictions from [this notebook](https://www.kaggle.com/code/vuonglam/lgbm-baseline-optuna-drop-constant-cite-task) by VuongLam.

submission.reset_index(drop=True, inplace=True)
submission.index.name = 'row_id'
# with open("partial_submission_multi.pickle", 'wb') as f:
#     pickle.dump(submission, f)
# submission

cite_submission = pd.read_csv("../input/lgbm-baseline-optuna-drop-constant-cite-task/submission.csv")
cite_submission = cite_submission.set_index("row_id")
cite_submission = cite_submission["target"]

submission[submission.isnull()] = cite_submission[submission.isnull()]

submission

submission.isnull().any()

submission.to_csv("submission.csv")

# !head submission.csv