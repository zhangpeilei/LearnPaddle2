import numpy as np
import paddle
import paddle.fluid as fluid
import matplotlib.pyplot as plt


# 定义生成器
def Generator(y, name="G"):
    with fluid.unique_name.guard(name + "/"):
        y = fluid.layers.fc(y, size=1024, act='tanh')
        y = fluid.layers.fc(y, size=128 * 7 * 7)
        y = fluid.layers.batch_norm(y, act='tanh')
        y = fluid.layers.reshape(y, shape=(-1, 128, 7, 7))

        y = fluid.layers.image_resize(y, scale=2)
        y = fluid.layers.conv2d(y, num_filters=64, filter_size=5, padding=2, act='tanh')

        y = fluid.layers.image_resize(y, scale=2)
        y = fluid.layers.conv2d(y, num_filters=1, filter_size=5, padding=2, act='tanh')

    return y


# 判别器 Discriminator
def Discriminator(images, name="D"):
    def conv_bn(input, num_filters, filter_size):
        y = fluid.layers.conv2d(
            input,
            num_filters=num_filters,
            filter_size=filter_size,
            padding=0,
            stride=1,
            bias_attr=False)
        y = fluid.layers.batch_norm(y)
        y = fluid.layers.leaky_relu(y)
        return y

    with fluid.unique_name.guard(name + "/"):
        y = images

        y = conv_bn(y, num_filters=32, filter_size=3)
        y = fluid.layers.pool2d(y, pool_size=2, pool_stride=2)

        y = conv_bn(y, num_filters=64, filter_size=3)
        y = fluid.layers.pool2d(y, pool_size=2, pool_stride=2)

        y = conv_bn(y, num_filters=128, filter_size=3)
        y = fluid.layers.pool2d(y, pool_size=2, pool_stride=2)

        y = fluid.layers.fc(y, size=1)

    return y


# 创建判别器D识别生成器G生成的假图片程序
train_d_fake = fluid.Program()
# 创建判别器D识别真实图片程序
train_d_real = fluid.Program()
# 创建生成器G生成符合判别器D的程序
train_g = fluid.Program()

# 创建共同的一个初始化的程序
startup = fluid.Program()

# 噪声维度
z_dim = 100


# 从Program获取prefix开头的参数名字
def get_params(program, prefix):
    all_params = program.global_block().all_parameters()
    return [t.name for t in all_params if t.name.startswith(prefix)]


# 训练判别器D识别真实图片
with fluid.program_guard(train_d_real, startup):
    # 创建读取真实数据集图片的data，并且label为1
    real_image = fluid.layers.data('image', shape=[1, 28, 28])
    ones = fluid.layers.fill_constant_batch_size_like(real_image, shape=[-1, 1], dtype='float32', value=1)

    # 判别器D判断真实图片的概率
    p_real = Discriminator(real_image)
    # 获取损失函数
    real_cost = fluid.layers.sigmoid_cross_entropy_with_logits(p_real, ones)
    real_avg_cost = fluid.layers.mean(real_cost)

    # 获取判别器D的参数
    d_params = get_params(train_d_real, "D")

    # 创建优化方法
    optimizer = fluid.optimizer.Adam(learning_rate=0.0002)
    optimizer.minimize(real_avg_cost, parameter_list=d_params)

# 训练判别器D识别生成器G生成的图片为假图片
with fluid.program_guard(train_d_fake, startup):
    # 利用创建假的图片data，并且label为0
    z = fluid.layers.data(name='z', shape=[z_dim, 1, 1])

    # 判别器D判断假图片的概率
    p_fake = Discriminator(Generator(z))
    zeros = fluid.layers.fill_constant_batch_size_like(z, shape=[-1, 1], dtype='float32', value=0)

    # 获取损失函数
    fake_cost = fluid.layers.sigmoid_cross_entropy_with_logits(p_fake, zeros)
    fake_avg_cost = fluid.layers.mean(fake_cost)

    # 获取判别器D的参数
    d_params = get_params(train_d_fake, "D")

    # 创建优化方法
    optimizer = fluid.optimizer.Adam(learning_rate=0.0002)
    optimizer.minimize(fake_avg_cost, parameter_list=d_params)

# 训练生成器G生成符合判别器D标准的假图片
with fluid.program_guard(train_g, startup):
    # 噪声
    z = fluid.layers.data(name='z', shape=[z_dim, 1, 1])

    # 生成图片
    fake = Generator(z)
    infer_program = train_g.clone(for_test=True)
    # 生成图片为真实图片的概率，Label为1
    p = Discriminator(fake)
    ones = fluid.layers.fill_constant_batch_size_like(z, shape=[-1, 1], dtype='float32', value=1)
    # 损失
    g_loss = fluid.layers.mean(fluid.layers.sigmoid_cross_entropy_with_logits(p, ones))

    # 获取G的参数
    g_params = get_params(train_g, "G")

    # 只训练G
    optimizer = fluid.optimizer.Adam(learning_rate=0.0002)
    optimizer.minimize(g_loss, parameter_list=g_params)


# 噪声生成
def z_reader():
    while True:
        yield np.random.normal(0.0, 1.0, (z_dim, 1, 1)).astype('float32')


# 读取MNIST数据集，不使用label
def mnist_reader(reader):
    def r():
        for img, label in reader():
            yield img.reshape(1, 28, 28)

    return r


# 显示图片
def show_image_grid(images, epoch=None):
    # fig = plt.figure(figsize=(5, 5))
    # fig.suptitle("Epoch {}".format(epoch))
    # gs = plt.GridSpec(8, 8)
    # gs.update(wspace=0.05, hspace=0.05)

    for i, image in enumerate(images[:64]):
        plt.imsave("test_%d.png" % i, image[0])
    #     ax = plt.subplot(gs[i])
    #     plt.axis('off')
    #     ax.set_xticklabels([])
    #     ax.set_yticklabels([])
    #     ax.set_aspect('equal')
    #     plt.imshow(image[0], cmap='Greys_r')
    # plt.show()


# 生成真实图片reader
mnist_generator = paddle.batch(
    paddle.reader.shuffle(mnist_reader(paddle.dataset.mnist.train()), 1024), batch_size=128)
# 生成假图片的reader
z_generator = paddle.batch(z_reader, batch_size=128)()

# 生成解析器
# place = fluid.CPUPlace()
place = fluid.CUDAPlace(0)
exe = fluid.Executor(place)
# 初始化参数
exe.run(startup)

# 测试噪声
test_z = np.array(next(z_generator))

# 开始训练
for epoch in range(30):
    for i, real_image in enumerate(mnist_generator()):
        # 训练判别器D识别真实图片
        r_fake = exe.run(program=train_d_fake,
                         fetch_list=[avg_cost],
                         feed={'z': np.array(next(z_generator))})

        # 训练判别器D识别生成器G生成的假图片
        r_real = exe.run(program=train_d_real,
                         fetch_list=[avg_cost],
                         feed={'image': np.array(real_image)})

        # 训练生成器G生成符合判别器D标准的假图片
        r_g = exe.run(program=train_g,
                      fetch_list=[g_loss],
                      feed={'z': np.array(next(z_generator))})
    print(epoch)

    # 测试生成的图片
    r_i = exe.run(program=infer_program,
                  fetch_list=[fake],
                  feed={'z': test_z})

    # 显示生成的图片
    show_image_grid(r_i[0], epoch)
