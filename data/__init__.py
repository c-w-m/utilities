import tensorflow_datasets as tfds
import tensorflow as tf
import numpy as np
import os


def get_dataset_pipeline(name, batch_size, test_batch_size):
    return prep_iterator(*load_datasets(name, batch_size, test_batch_size))

def load_datasets(name, batch_size, test_batch_size):
    splits, ds_info = tfds.load(name, with_info=True)
    train_size = ds_info.splits['train'].num_examples
    test_size = ds_info.splits['test'].num_examples
    train_ds = splits['train'].shuffle(train_size).repeat().batch(batch_size).prefetch(4)
    test_ds = splits['test']
    if test_batch_size<=0:
        test_ds = test_ds.shuffle(test_size).repeat().batch(test_size).prefetch(2)
    else:
        test_ds = test_ds.repeat().batch(test_batch_size).prefetch(2)

    # fig = tfds.show_examples(ds_info, test_ds)
    return train_ds, test_ds

def prep_iterator(train_ds, test_ds):
    iter_train_handle = train_ds.make_one_shot_iterator().string_handle()
    iter_test_handle = test_ds.make_one_shot_iterator().string_handle()

    handle = tf.placeholder(tf.string, shape=[])
    iterator = tf.data.Iterator.from_string_handle(handle, tf.compat.v1.data.get_output_types(train_ds), tf.compat.v1.data.get_output_shapes(train_ds))
    next_batch = iterator.get_next()
    x_, y_ = tf.cast(next_batch['image'], tf.float32)/255.0, next_batch['label']

    def init_call(sess):
        init_call.train, init_call.test = sess.run([iter_train_handle, iter_test_handle])

    get_train_fd = lambda: {handle: init_call.train}
    get_test_fd = lambda: {handle: init_call.test}

    return (x_, y_), (get_train_fd, get_test_fd), init_call


def merge_feed_dicts(*train_test_dicts_list):
    ret_callers = []
    train_list_test_list = list(zip(*train_test_dicts_list))
    for feed_dict_list in train_list_test_list:
        # https://stackoverflow.com/questions/3431676/creating-functions-in-a-loop
        # need early binding within a for loop
        def get_fd_call(feed_dict_list=feed_dict_list):
            merged_dict = {}
            for feed_dict in feed_dict_list:
                if callable(feed_dict): feed_dict = feed_dict()
                merged_dict.update(feed_dict)
            return merged_dict
        ret_callers.append(get_fd_call)
    return ret_callers


# depricated - the old way of loading data with keras
def get_dataset(name):
    # Keras automatically creates a cache directory in ~/.keras/datasets for
    # storing the downloaded MNIST data. This creates a race
    # condition among the workers that share the same filesystem. If the
    # directory already exists by the time this worker gets around to creating
    # it, ignore the resulting exception and continue.
    cache_dir = os.path.join(os.path.expanduser('~'), '.keras', 'datasets')
    if not os.path.exists(cache_dir):
        try:
            os.mkdir(cache_dir)
        except OSError as e:
            if e.errno == errno.EEXIST and os.path.isdir(cache_dir):
                pass
            else:
                raise

    from tensorflow import keras
    (x_train, y_train), (x_test, y_test) = getattr(keras.datasets, name).load_data()
    x_train = x_train/255.0
    x_test = x_test/255.0
    return (x_train, np.squeeze(y_train)), (x_test, np.squeeze(y_test))

def permute(x_, y_, seed=None):
    p = np.random.RandomState(seed=seed).permutation(len(x_))
    return x_[p], y_[p]

def input_generator(x_train, y_train, batch_size):
    while True:
        x_train, y_train = permute(x_train, y_train)
        index = 0
        while index <= len(x_train) - batch_size:
            yield x_train[index:index + batch_size], \
                  y_train[index:index + batch_size],
            index += batch_size

def random_subset(x_test, y_test, test_size):
    x_test, y_test = permute(x_test, y_test)
    return x_test[:test_size], y_test[:test_size]


def compute_metrics_inner(logits, target, correct_pred):
    num_classes = logits.shape[-1]
    target_1h = tf.one_hot(tf.cast(target, tf.int32), num_classes)
    losses = tf.losses.softmax_cross_entropy(target_1h, logits, reduction='none')
    sum_loss = tf.reduce_sum(losses)
    avg_loss = tf.reduce_mean(losses)
    accuracy = tf.reduce_mean(tf.cast(correct_pred, tf.float32), name='accuracy')
    return accuracy, sum_loss, avg_loss

def compute_metrics_topk(logits, target, k):
    correct_pred = tf.nn.in_top_k(predictions=logits, targets=target, k=k)
    return compute_metrics_inner(logits, target, correct_pred)

def compute_metrics(logits, target):
    correct_pred = tf.equal(tf.argmax(logits, 1), tf.cast(target, 'int64'))
    return compute_metrics_inner(logits, target, correct_pred)


def l2_reg_loss(var_list):
    return tf.add_n([tf.nn.l2_loss(v) for v in var_list])