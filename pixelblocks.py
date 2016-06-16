""" Implementing pixelCNN in Blocks"""
import sys
from theano import tensor as T

from blocks.algorithms import GradientDescent, Adam, RMSProp
from blocks.bricks.base import application
from blocks.bricks.conv import ConvolutionalSequence, Convolutional
from blocks.bricks import Rectifier, Softmax
from blocks.bricks.cost import CategoricalCrossEntropy
from blocks.initialization import IsotropicGaussian, Constant
from blocks.main_loop import MainLoop
from blocks.model import Model
from blocks.extensions import FinishAfter, Printing, ProgressBar
from blocks.extensions.stopping import FinishIfNoImprovementAfter
from blocks.extensions.monitoring import DataStreamMonitoring, TrainingDataMonitoring
from blocks.extensions.saveload import Checkpoint, Load

from fuel.datasets import MNIST
from fuel.streams import DataStream
from fuel.schemes import ShuffledScheme
from fuel.transformers import Flatten


sys.setrecursionlimit(500000)

batch_size = 16
mnist_dim = 28
nb_epoch = 100
n_channel = 1
patience = 3
path = '/data/lisa/exp/alitaiga/Generative-models'
sources = ('features',)

MODE = '256ary'  # choice with 'binary' and '256ary

if MODE == 'binary':
    activation = 'sigmoid'
    loss = 'binary_crossentropy'
elif MODE == '256ary':
    activation = 'softmax'
    loss = 'categorical_crossentropy'
n_layer = 6
res_connections = True
first_layer = ((7, 7), 32, n_channel)
second_layer = ((3, 3), 32, 32)
third_layer = (256 if MODE == '256ary' else 1, 1, 1)

class ConvolutionalNoFlip(Convolutional) :
    @application(inputs=['input_'], outputs=['output'])
    def apply(self, input_):
        """Perform the convolution.

        Parameters
        ----------
        input_ : :class:`~tensor.TensorVariable`
            A 4D tensor with the axes representing batch size, number of
            channels, image height, and image width.

        Returns
        -------
        output : :class:`~tensor.TensorVariable`
            A 4D tensor of filtered images (feature maps) with dimensions
            representing batch size, number of filters, feature map height,
            and feature map width.

            The height and width of the feature map depend on the border
            mode. For 'valid' it is ``image_size - filter_size + 1`` while
            for 'full' it is ``image_size + filter_size - 1``.

        """
        if self.image_size == (None, None):
            input_shape = None
        else:
            input_shape = (self.batch_size, self.num_channels)
            input_shape += self.image_size

        output = self.conv2d_impl(
            input_, self.W,
            input_shape=input_shape,
            subsample=self.step,
            border_mode=self.border_mode,
            filter_shape=((self.num_filters, self.num_channels) +
                           self.filter_size),
            filter_flip=False)
        if getattr(self, 'use_bias', True):
            if self.tied_biases:
                output += self.b.dimshuffle('x', 0, 'x', 'x')
            else:
                output += self.b.dimshuffle('x', 0, 1, 2)
        return output

def create_network():
    # Creating pixelCNN architecture
    inputs = T.matrix('features')
    y = T.lmatrix('features')
    conv_list = [ConvolutionalNoFlip(*first_layer)]
    for i in range(n_layer):
        conv_list.extend([ConvolutionalNoFlip(*second_layer), Rectifier()])

    conv_list.extend([ConvolutionalNoFlip((3,3), 64, 32), Rectifier()])
    conv_list.extend([ConvolutionalNoFlip((3,3), 64, 64), Rectifier()])
    conv_list.extend([ConvolutionalNoFlip((1,1), 128, 64), Rectifier()])
    conv_list.extend([ConvolutionalNoFlip((1,1), 256, 128)])

    model = ConvolutionalSequence(
        conv_list,
        num_channels=1,
        batch_size=batch_size,
        image_size=(mnist_dim,mnist_dim),
        border_mode='half',
        weights_init=IsotropicGaussian(std=0.05, mean=0),
        biases_init=Constant(0.02),
        tied_biases=False
    )
    model.initialize()
    x = model.apply(inputs)
    x = x.dimshuffle(1,0,2,3)
    x = x.flatten(ndim=3)
    x = x.flatten(ndim=2)
    x = x.dimshuffle(1,0)
    y_hat = Softmax().apply(x)

    cost = CategoricalCrossEntropy().apply(y.flatten(), y_hat)
    cost.name = 'cross_entropy'
    return cost

def prepare_opti(cost, test):
    model = Model(cost)
    print "Model created"

    algorithm = GradientDescent(
        cost=cost,
        parameters=model.parameters,
        step_rule=Adam(),
        on_unused_sources='ignore'
    )
    extensions = [
        FinishAfter(after_n_epochs=nb_epoch),
        FinishIfNoImprovementAfter(notification_name='test_cross_entropy', epochs=patience),
        TrainingDataMonitoring(
            [algorithm.cost],
            prefix="train",
            after_epoch=True),
        DataStreamMonitoring(
            [algorithm.cost],
            test_stream,
            prefix="test"),
        Printing(),
        ProgressBar(),
        Checkpoint(path, after_epoch=True)
    ]
    return model, algorithm, extensions

if __name__ == '__main__':
    mnist = MNIST(("train",))
    mnist_test = MNIST(("test",))
    training_stream = Flatten(
        DataStream.default_stream(
            mnist,
            iteration_scheme=ShuffledScheme(mnist.num_examples, batch_size)
        ),
        which_sources='features'
    )
    test_stream = Flatten(
        DataStream.default_stream(
            mnist_test,
            iteration_scheme=ShuffledScheme(mnist_test.num_examples, batch_size)
        ),
        which_sources='features'
    )
    "Print data loaded"

    cost = create_network()
    model, algorithm, extensions = prepare_opti(cost, test_stream)

    main_loop = MainLoop(
        algorithm=algorithm,
        data_stream=training_stream,
        model=model,
        extensions=extensions
    )