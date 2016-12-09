# Copyright (c) Microsoft. All rights reserved.

# Licensed under the MIT license. See LICENSE.md file in the project root
# for full license information.
# ==============================================================================

import numpy as np
import scipy.sparse as sparse
csr = sparse.csr_matrix
import pytest

from cntk.device import default
from cntk.tests.test_utils import precision, PRECISION_TO_TYPE
from cntk.ops import *
from cntk.utils import *
from cntk.utils import _has_seq_dim

AA = np.asarray

def test_sanitize_dtype_numpy():
    for dtype in ['float', 'float32', np.float32, int]:
        assert sanitize_dtype_numpy(dtype) == np.float32, dtype
    for dtype in [float, 'float64', np.float64]:
        assert sanitize_dtype_numpy(dtype) == np.float64, dtype

def test_sanitize_dtype_cntk():
    for dtype in ['float', 'float32', np.float32, int]:
        assert sanitize_dtype_cntk(dtype) == cntk_py.DataType_Float, dtype
    for dtype in [float, 'float64', np.float64]:
        assert sanitize_dtype_cntk(dtype) == cntk_py.DataType_Double, dtype

@pytest.mark.parametrize("data, dtype", [
    ([1], np.float32),
    ([[1, 2]], np.float64),
    (2, np.float64),
    (AA([1,2], dtype=np.float32), np.float64),
])
def test_sanitize_input(data, dtype):
    inp = sanitize_input(data, dtype)
    assert np.allclose(inp.value, data)
    assert inp.dtype == dtype

def test_axes():
    axes = [Axis.default_batch_axis(), Axis.default_dynamic_axis()]
    assert tuple(axes) == Axis.default_input_variable_dynamic_axes()
    assert sanitize_dynamic_axes(axes) == \
            tuple(reversed(Axis.default_input_variable_dynamic_axes()))

    assert (Axis.default_dynamic_axis(),) == \
            sanitize_dynamic_axes(Axis.default_dynamic_axis())
    
def test_get_data_type():
    pa32 = parameter(init=np.asarray(2, dtype=np.float32))
    pa64 = parameter(init=np.asarray(2, dtype=np.float64))
    pl = placeholder_variable(shape=(2))
    c = constant(value=3.0)
    n32 = AA(1, dtype=np.float32)
    n64 = AA(1, dtype=np.float64)

    assert get_data_type(pa32) == np.float32
    assert get_data_type(pa32, n32) == np.float32
    assert get_data_type(n32, n32) == np.float32
    assert get_data_type(n32, n64) == np.float64
    assert get_data_type(pl, n64) == np.float64
    assert get_data_type(pl, n32) == np.float32
    assert get_data_type(pl, pl) == None
    # variable's type shall take precedence over provided data
    assert get_data_type(pa32, n64) == np.float32
    assert get_data_type(pa64, n64) == np.float64
    assert get_data_type(pa32, pl, n64) == np.float32
    assert get_data_type(pa64, pl, n64) == np.float64

def test_sanitize_batch_sparse():
    batch = [csr([[1,0,2],[2,3,0]]),
             csr([5,0,1])]

    var = input_variable(3, is_sparse=True)
    b = sanitize_batch(var, batch)
    # 2 sequences, with max seq len of 2 and dimension 3
    assert b.shape == (2,2,3)

    var = input_variable((1,3), is_sparse=True)
    b = sanitize_batch(var, batch)
    # 2 sequences, with max seq len of 2 and dimension 3
    assert b.shape == (2,2,3)

@pytest.mark.parametrize("batch, seq_starts, expected", [
    ([AA([5, 6, 7]), AA([8])],
       [True, False],
       [[2, 1, 1], [1, 0, 0]]),

    ([AA([5]), AA([8])],
       [True, False],
       [[2], [1]]),

    # exception handling
    ([[5, 6, 7], [8]],
       [True, False],
       ValueError),
])
def test_mask(batch, seq_starts, expected):
    shape = (1,)
    var = input_variable(shape)
    if type(expected) == type(ValueError):
        with pytest.raises(expected):
            s = sanitize_batch(var, batch, seq_starts)
    else:
        s = sanitize_batch(var, batch, seq_starts)
        assert np.allclose(s.mask, expected)

def test_sanitize_batch_contiguity():
    a1 = AA([[1,2],[3,4]])
    a2 = AA([[5,6],[7,8]])
    var = input_variable((2,2), is_sparse=True)

    batch = [a1.T,a2.T]
    with pytest.raises(ValueError):
        b = sanitize_batch(var, batch)

    batch = [[a1],[a2]]
    b = sanitize_batch(var, batch)
    assert b.shape == (2,1,2,2)

@pytest.mark.parametrize("data", [
    # TODO: uncomment when arrays represent several samples. The same as for sparse test below
    #([[AA([4., 5, 6., 7., 8.])], # dense sequences with different lengths
    #  [AA([[4., 5, 6., 7., 8.],[4., 5, 6., 7., 8.]])]]),
    ([AA([4., 5, 6., 7., 8.]), # dense sequence with two samples
      AA([4., 5, 6., 7., 8.])]),
    ([[AA([4., 5, 6., 7., 8.])], # dense sequences with same length
      [AA([4., 5, 6., 7., 8.])]]),
])

def test_dense_value_to_ndarray(data):
    shape = (5,)
    var = input_variable(shape)
    val = sanitize_batch(var, data)

    dense_val = val.to_ndarray()

    for input_data, nd_val in zip(data, dense_val):
        assert AA(input_data).shape == nd_val.shape
        assert np.allclose(input_data, nd_val)

@pytest.mark.parametrize("data, expected_csr_shape", [
    #([[csr([[1,0,2],[2,3,0]])], # sparse sequences with different lengths
    #  [csr([5,0,1])]], [(2,3),(1,3)]),
    ([[csr([1,0,2])], # sparse sequences with same length
      [csr([5,0,1])]], [(1,3),(1,3)]),
    (csr([[1,0,2],[2,3,4]]), [(2,3)]) # sparse squence with two samples
])

def test_sparse_value_to_csr(data, expected_csr_shape):
    shape = (3,)
    var = input_variable(shape, is_sparse=True)
    val = sanitize_batch(var, data)

    csr_val = val.to_csr()

    csr_val_shapes = [ v.shape for v in csr_val]

    assert csr_val_shapes == expected_csr_shape

def test_one_hot_val_to_csr():
    one_hot_val = one_hot([[1,2,0,4,3],[3,4]],5)
    expected_csr_shape = [(5,5), (2,5)]

    csr_val = one_hot_val.to_csr()

    csr_val_shapes = [ v.shape for v in csr_val]

    assert csr_val_shapes == expected_csr_shape

def test_valid_to_csr_or_ndarrray():
    # dense to csr
    data = [[AA(np.reshape(np.arange(12.0), (3,4)))]]
    shape = (3,4)
    var = input_variable(shape)

    val = sanitize_batch(var, data)

    with pytest.raises(ValueError):
        val.to_csr()

    assert isinstance(val.to_ndarray(), np.ndarray)

    # sparse to ndarray
    data_sparse = [csr([[1,0,2],[2,3,0]])]
    shape = (3,)
    var = input_variable(shape, is_sparse=True)
    
    val = sanitize_batch(var, data_sparse)
    
    with pytest.raises(ValueError):
        val.to_ndarray()
    
    assert isinstance(val.to_csr(), list)
