import sys,os
import math
import owl
import owl.elewise as ele
import owl.conv as co
import numpy as np
import mnist_io

# PS
import ps
bulk = True

class MnistTrainer:
    def __init__(self, data_file='mnist_all.mat', num_epochs=100, mb_size=256, eps_w=0.01, eps_b=0.01):
        print('Worker; NodeID: %s, Rank: %d, RankSize: %d' % (ps.my_node_id, ps.my_rank, ps.rank_size))

        self.cpu = owl.create_cpu_device()
        # PS: for local tes
        #self.gpu = owl.create_gpu_device(0)
        self.gpu = owl.create_gpu_device(ps.my_rank % owl.get_gpu_device_count())
        self.data_file = data_file
        self.num_epochs=num_epochs
        self.mb_size=mb_size
        self.eps_w=eps_w
        self.eps_b=eps_b
        # init weight
        l1 = 784; l2 = 256; l3 = 10
        # PS: pull weights from servers
        # self.l1 = l1; self.l2 = l2; self.l3 = l3
        # self.w1 = owl.randn([l2, l1], 0.0, math.sqrt(4.0 / (l1 + l2)))
        # self.w2 = owl.randn([l3, l2], 0.0, math.sqrt(4.0 / (l2 + l3)))
        # self.b1 = owl.zeros([l2, 1])
        # self.b2 = owl.zeros([l3, 1])
        self.w1 = ps.pull_weight(owl.zeros([l2, l1]), 'w1')
        self.w2 = ps.pull_weight(owl.zeros([l3, l2]), 'w2')
        self.b1 = ps.pull_weight(owl.zeros([l2, 1]), 'b1')
        self.b2 = ps.pull_weight(owl.zeros([l3, 1]), 'b2')

        if bulk:
            self.gw1 = owl.zeros([l2, l1])
            self.gw2 = owl.zeros([l3, l2])
            self.gb1 = owl.zeros([l2, 1])
            self.gb2 = owl.zeros([l3, 1])

    def run(self):
        (train_data, test_data) = mnist_io.load_mb_from_mat(self.data_file, self.mb_size)
        np.set_printoptions(linewidth=200)
        num_test_samples = test_data[0].shape[0]
        (test_samples, test_labels) = map(lambda npdata : owl.from_numpy(npdata), test_data)
        count = 1
        owl.set_device(self.gpu)
        for epoch in range(self.num_epochs):
            print '---Start epoch #%d' % epoch
            # train
            for idx, (mb_samples, mb_labels) in enumerate(train_data):
                if idx % ps.rank_size != ps.my_rank: continue

                num_samples = mb_samples.shape[0]

                a1 = owl.from_numpy(mb_samples)
                target = owl.from_numpy(mb_labels)

                # ff
                a2 = ele.relu(self.w1 * a1 + self.b1)
                a3 = self.w2 * a2 + self.b2
                # softmax & error
                out = co.softmax(a3)
                s3 = out - target
                # bp
                s2 = self.w2.trans() * s3
                s2 = ele.relu_back(s2, a2)
                # grad
                gw1 = s2 * a1.trans() / num_samples
                gb1 = s2.sum(1) / num_samples
                gw2 = s3 * a2.trans() / num_samples
                gb2 = s3.sum(1) / num_samples
                # update
                # PS: update weights on the server
                #self.w1 -= self.eps_w * gw1
                #self.w2 -= self.eps_w * gw2
                #self.b1 -= self.eps_b * gb1
                #self.b2 -= self.eps_b * gb2
                if not bulk:
                    self.w1 = ps.push_grad_and_pull_weight(gw1, self.w1, 'w1')
                    self.w2 = ps.push_grad_and_pull_weight(gw2, self.w2, 'w2')
                    self.b1 = ps.push_grad_and_pull_weight(gb1, self.b1, 'b1')
                    self.b2 = ps.push_grad_and_pull_weight(gb2, self.b2, 'b2')
                else:
                    self.gw1 += gw1
                    self.gw2 += gw2
                    self.gb1 += gb1
                    self.gb2 += gb2
                    if count % 10 == 0:
                        self.w1 = ps.push_grad_and_pull_weight(self.gw1, self.w1, 'w1')
                        self.w2 = ps.push_grad_and_pull_weight(self.gw2, self.w2, 'w2')
                        self.b1 = ps.push_grad_and_pull_weight(self.gb1, self.b1, 'b1')
                        self.b2 = ps.push_grad_and_pull_weight(self.gb2, self.b2, 'b2')
                        self.gw1 -= self.gw1
                        self.gw2 -= self.gw2
                        self.gb1 -= self.gb1
                        self.gb2 -= self.gb2

                if (count % 40 == 0):
                    correct = out.argmax(0) - target.argmax(0)
                    val = correct.to_numpy()
                    print 'Training error:', float(np.count_nonzero(val)) / num_samples
                count = count + 1

            if bulk:
                self.w1 = ps.push_grad_and_pull_weight(self.gw1, self.w1, 'w1')
                self.w2 = ps.push_grad_and_pull_weight(self.gw2, self.w2, 'w2')
                self.b1 = ps.push_grad_and_pull_weight(self.gb1, self.b1, 'b1')
                self.b2 = ps.push_grad_and_pull_weight(self.gb2, self.b2, 'b2')

            # test
            a1 = test_samples
            a2 = ele.relu(self.w1 * a1 + self.b1)
            a3 = self.w2 * a2 + self.b2
            correct = a3.argmax(0) - test_labels.argmax(0)
            val = correct.to_numpy()
            #print val
            print 'Testing error:', float(np.count_nonzero(val)) / num_test_samples
            print '---Finish epoch #%d' % epoch



class MnistServer:
    def __init__(self):
        print('Server; NodeID: %s, Rank: %d, RankSize: %d' % (ps.my_node_id, ps.my_rank, ps.rank_size))
        self.cpu = owl.create_cpu_device()

    def init_layer(self, name, weight):
        l1 = 784; l2 = 256; l3 = 10

        w1 = owl.randn([l2, l1], 0.0, math.sqrt(4.0 / (l1 + l2)))
        w2 = owl.randn([l3, l2], 0.0, math.sqrt(4.0 / (l2 + l3)))
        b1 = owl.zeros([l2, 1])
        b2 = owl.zeros([l3, 1])

        if name == 'w1':
            np.copyto(weight, w1.to_numpy().flatten())
        elif name == 'w2':
            np.copyto(weight, w2.to_numpy().flatten())
        elif name == 'b1':
            np.copyto(weight, b1.to_numpy().flatten())
        elif name == 'b2':
            np.copyto(weight, b2.to_numpy().flatten())
        else:
            assert False

    def update_layer(self, name, weight, gradient):
        eps_w = 0.01
        eps_b = 0.01

        if name[0] == 'w':
            weight -= eps_w * gradient
        elif name[0] == 'b':
            weight -= eps_b * gradient
        else:
            assert False


# PS: server
server = None
def server_node_init():
    global server
    owl.initialize(sys.argv + ['-no_init_glog'])
    server = MnistServer()

def server_init_layer(name, weight):
    server.init_layer(name, weight)

def server_update_layer(name, weight, gradient):
    server.update_layer(name, weight, gradient)

# PS: worker
worker = None
def worker_node_init():
    global worker
    owl.initialize(sys.argv + ['-no_init_glog'])
    worker = MnistTrainer(num_epochs = 10)

def worker_node_main():
    worker.run()

if __name__ == '__main__':
    pass

