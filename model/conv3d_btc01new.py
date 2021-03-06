"""
The functionality in this module is very similar to that in
pylearn2.linear.conv2d. The difference is that this module is
based on Alex Krizhevsky's cuda-convnet convolution, while
pylearn2.linear.conv2d is based on theano's 2D convolution.
This module therefore uses the axis format ('c', 0, 1, 'b')
as its native format, while the other uses ('b', 'c', 0, 1).
This module also requires the use of GPU, while the other
supports CPU.
"""
__authors__ = "Mehdi Mirza, Ian Goodfellow"
__copyright__ = "Copyright 2010-2012, Universite de Montreal"
__credits__ = ["Mehdi Mirza", "Ian Goodfellow"]
__license__ = "3-clause BSD"
__maintainer__ = "Mehdi Mirza"
__email__ = "mirzamom@iro"

import functools
import numpy as np
import warnings
import math
import theano
from theano.sandbox import cuda
import theano.tensor as T

if cuda.cuda_enabled:
    from theano.sandbox.cuda.basic_ops import gpu_contiguous
    from theano.sandbox.cuda import gpu_from_host
    from theano.sandbox.cuda import host_from_gpu

from pylearn2.utils import sharedX
from pylearn2.utils.rng import make_np_rng
from pylearn2.linear.conv2d import default_seed, default_sparse_seed
from pylearn2.linear.linear_transform import LinearTransform
from pylearn2.sandbox.cuda_convnet import check_cuda
#from pylearn2.space import Conv3DSpace
from HumanActivityRecognition.space import Conv3DSpace

#from theano.tensor.nnet.Conv3D import Conv3D
from HumanActivityRecognition.model.corr3d2d import conv3d


def random_matrix(shape, np_rng, name=None):
        return theano.shared(np.require(np_rng.randn(*shape), dtype=floatX),
                        borrow=True, name=name)


class ScikitsCudaOp(cuda.GpuOp): # base class for shared code between scikits.cuda-based ops
    def __eq__(self, other):
        return type(self) == type(other)

    def __hash__(self):
        return hash(type(self))

    def __str__(self):
        return self.__class__.__name__

    def output_type(self, inp):
        raise NotImplementedError

    def make_node(self, inp):
        inp = cuda.basic_ops.gpu_contiguous(
           cuda.basic_ops.as_cuda_ndarray_variable(inp))

        assert inp.dtype == "float32"

        return theano.Apply(self, [inp], [self.output_type(inp)()])



class ShapePrint(ScikitsCudaOp):
    def output_type(self, inp):
        return cuda.CudaNdarrayType(broadcastable=[False] * (inp.type.ndim))

    def make_thunk(self, node, storage_map, _, _2):
        inputs = [storage_map[v] for v in node.inputs]
        outputs = [storage_map[v] for v in node.outputs]

        def thunk():
            input_shape = inputs[0][0].shape
            print input_shape
            outputs[0] = inputs[0]

        thunk.inputs = inputs
        thunk.outputs = outputs
        thunk.lazy = False
        return thunk


shapeprint = ShapePrint()



class Conv3DB01TC(LinearTransform):
    """
    A pylearn2 linear operator based on theano 3D convolution,

    """

    def __init__(self,
                 filters,
                 signal_shape,
                 filter_shape,
                 input_axes = ('b', 0, 1, 't', 'c'),
                 batch_size=None,
                 output_axes = ('b', 0, 1, 't', 'c'),
                 kernel_stride = [1, 1, 1],
                 pad=0,
                 message = '',
                 partial_sum=None):

        if len(kernel_stride) != 3:
            raise ValueError("kernel_stride must have length 3")
        elif kernel_stride[0] != kernel_stride[1]:
            raise ValueError("only values of kernel_stride with both "
                             "elements equal are supported currently")
        if message != '':
            raise NotImplementedError()

        if batch_size != None:
            raise NotImplementedError()

        if input_axes != ('b', 0, 1, 't', 'c'):
            raise NotImplementedError()

        print kernel_stride
        #if kernel_stride != (1, 1, 1):
        #    raise ValueError("only values of kernel_stride with value of 1 "
        #                     " are supported currently")

        self.input_axes = input_axes
        self.output_axes = output_axes

        #self.conv3d_op = Conv3D()
        #self.conv3d_op = conv3d()

        # filters should be a GPU shared variable.
        # I guess you could GpuFromHost them every time,
        # but if you're using this class you probably care
        # about performance and want to be at least warned
        # that this is happening
        assert hasattr(filters, 'get_value')
        assert 'Cuda' in str(type(filters))
        self._filters = filters
        self.pad = pad
        self.partial_sum = partial_sum
        self.kernel_stride = kernel_stride
        #self.kernel_stride = [1,1,1]
        self.signal_shape = signal_shape
        self.filter_shape = filter_shape

        ## Add a dummy b for interface issue
        self.b = sharedX(np.zeros((filter_shape[0])))



    @functools.wraps(LinearTransform.get_params)
    def get_params(self):
        return [self._filters]

    @functools.wraps(LinearTransform.get_weights_topo)
    def get_weights_topo(self, borrow=False):
        # TODO what would be real weight topo?!
        inp, rows, cols, outp = range(4)
        raw = self._filters.get_value(borrow=borrow)
        return np.transpose(raw, (outp, rows, cols, inp))

    def lmul(self, x):
        """
        dot(x, A)
        aka, do convolution with input image x

        """

        check_cuda(str(type(self)) + ".lmul")
        cpu = 'Cuda' not in str(type(x))
        assert cpu
        if cpu:
            x = gpu_from_host(x)

        assert x.ndim == 5
        x_axes = self.input_axes
        assert len(x_axes) == 5

        #x = shapeprint(x)
        op_axes = ('b', 0, 1, 't', 'c')
        print x_axes, op_axes
        if tuple(x_axes) != op_axes:
            x = x.dimshuffle(*[x_axes.index(axis) for axis in op_axes])

        #x = shapeprint(x)
        #self._filters = shapeprint(self._filters)

        im = x.dimshuffle(0,3,4,1,2)
        filt = self._filters.dimshuffle(0,3,4,1,2)
       
        rval = conv3d(im, filt, None, None, (self.kernel_stride[0], self.kernel_stride[1]) )
       
        rval = rval.dimshuffle(0,3,4,1,2)
        
        return rval

    def lmul_T(self, x):
        raise NotImplementedError()

    def lmul_sq_T(self, x):
        raise NotImplementedError()

    def set_batch_size(self, batch_size):
        pass

def make_random_conv3D(irange,
                       input_axes, output_axes,
                       signal_shape, filter_shape,
                       kernel_stride = (2,2,1), pad=0,
                       message = "", rng = None,
                       partial_sum = None):
    if rng is None:
        rng = make_np_rng(rng, default_seed, which_method='uniform')

    ### b 0 1 t c
    _filter_5d_shape = (
        filter_shape[0],
        filter_shape[1],
        filter_shape[2],
        filter_shape[3],
        filter_shape[4])

    # initialize weights
    print(_filter_5d_shape)
    W = sharedX(rng.uniform(-irange,irange,(_filter_5d_shape)))
    print 'w is set'
    return Conv3DB01TC(filters = W,
                       input_axes = input_axes,
                       output_axes = output_axes,
                       signal_shape = signal_shape,
                       filter_shape = filter_shape,
                       kernel_stride = kernel_stride, pad=pad,
                       message = message, partial_sum=partial_sum)

def setup_detector_layer_b01tc(layer, input_space, rng, irange,stride):
    """
    Takes steps to set up an object for use as being some kind of
    convolutional layer.
    This function sets up only the detector layer.
    Parameters
    ----------
    layer: Any python object that allows the modifications described below and has
    the following attributes:
         pad: int describing amount of zero padding to add
         kernel_shape: 3-element tuple or list describing shape of kernel
         fix_kernel_shape: bool, if true, will shrink the kernel shape to make it
         feasible, as needed (useful for hyperparameter searchers)
         detector_channels: The number of channels in the detector layer
         init_bias: A numeric constant added to a tensor of zeros to initialize the
         bias
         tied_b: If true, biases are shared across all spatial locations

    input_space: A Conv3DSpace to be used as input to the layer

    rng: a numpy RandomState or equivalent

    irange: float. kernel elements are initialized randomly from U(-irange, irange)

    Does the following:
        raises a RuntimeError if cuda is not available
        sets layer.input_space to input_space
        sets up addition of dummy channels for compatibility with cuda-convnet:
            layer.dummy_channels: # of dummy channels that need to be added
                (You might want to check this and raise an Exception if it's not 0)
            layer.dummy_space: The Conv2DSpace representing the input with dummy channels
                added
        sets layer.detector_space to the space for the detector layer
        sets layer.transformer to be a Conv3DB01TC instance
        sets layer.b to the right value
    """

    # Use "self" to refer to layer from now on, so we can pretend we're just running
    # in the set_input_space method of the layer
    self = layer

    # Make sure cuda is available
    check_cuda(str(type(self)))

    # Validate input
    if not isinstance(input_space, Conv3DSpace):
        raise TypeError("The input to a convolutional layer should be a Conv3DSpace, "
                " but layer " + self.layer_name + " got "+str(type(self.input_space)))

    if not hasattr(self, 'detector_channels'):
        raise ValueError('layer argument must have a "detector_channels" attribute specifying how many channels to put in the convolution kernel stack.')

    # Store the input space
    self.input_space = input_space

    #self.dummy_space = Conv3DSpace(shape=input_space.shape,
    #                               channels=input_space.num_channels + self.dummy_channels,
    #                               axes=('b', 'c', 't', 0, 1))


    if hasattr(self, 'kernel_stride'):
        kernel_stride = stride
    else:
        kernel_stride = stride

    #import pdb; pdb.set_trace()
    #dummy_shape = [self.input_space.shape[0], self.input_space.shape[1] ]
    output_shape = [int((i_sh + 2. * self.pad - k_sh) / float(k_st)) +1
                    for i_sh, k_sh, k_st in zip(self.input_space.shape,
                                                self.kernel_shape,
                                                kernel_stride)]
										

    def handle_kernel_shape(idx):
        if self.kernel_shape[idx] < 1:
            raise ValueError("kernel must have strictly positive size on all axes but has shape: "+str(self.kernel_shape))
        if output_shape[idx] <= 0:
            if self.fix_kernel_shape:
                self.kernel_shape[idx] = self.input_space.shape[idx] + 2 * self.pad
                assert self.kernel_shape[idx] != 0
                output_shape[idx] = 1
                warnings.warn("Had to change the kernel shape to make network feasible")
            else:
                raise ValueError("kernel too big for input (even with zero padding)")
    map(handle_kernel_shape, [0, 1, 2])

    # space required for 3dconv
    self.detector_space = Conv3DSpace(shape=output_shape,
                                      num_channels = self.detector_channels,
                                      axes = ('b', 0, 1, 't', 'c'))

    if hasattr(self, 'partial_sum'):
        partial_sum = self.partial_sum
    else:
        partial_sum = 1
    # filter shape required for fft3dconv ('c_detector','c','t','0','1')
    filter_shape = (self.detector_space.num_channels,
                    self.kernel_shape[0],
                    self.kernel_shape[1],
                    self.kernel_shape[2],
                    self.input_space.num_channels,
                   )

    # filter shape required for fft-3dconv ('b','c','t','0','1')
    signal_shape = (self.mlp.batch_size,
                    self.input_space.shape[0],
                    self.input_space.shape[1],
                    self.input_space.shape[2],
                    self.input_space.num_channels,
                    )

    self.transformer = make_random_conv3D(
        irange = self.irange,
        input_axes = ('b', 0, 1, 't', 'c'),
        output_axes = self.detector_space.axes,
        signal_shape = signal_shape,
        filter_shape = filter_shape,
        pad = self.pad,
        partial_sum = partial_sum,
        kernel_stride = kernel_stride,
        rng = rng)

    W, = self.transformer.get_params()
    W.name = 'W'

    if self.tied_b:
        self.b = sharedX(np.zeros((self.detector_space.num_channels)) + self.init_bias)
    else:
        self.b = sharedX(self.detector_space.get_origin() + self.init_bias)
    self.b.name = 'b'



