"""
This is a modified version of the PyTorch MNIST example from
https://github.com/pytorch/examples/blob/main/mnist/main.py

It is subject to the below license.

------------------------------------------------------------------------------
BSD 3-Clause License

Copyright (c) 2017,
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

* Redistributions of source code must retain the above copyright notice, this
  list of conditions and the following disclaimer.

* Redistributions in binary form must reproduce the above copyright notice,
  this list of conditions and the following disclaimer in the documentation
  and/or other materials provided with the distribution.

* Neither the name of the copyright holder nor the names of its
  contributors may be used to endorse or promote products derived from
  this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""

import datetime
import os
import time

import torch
from torch.distributed import destroy_process_group, init_process_group
from torch.nn.parallel import DistributedDataParallel as DDP
from torch.utils.data.distributed import DistributedSampler

from mnist_model import Net, get_mnist_setup, train, test
from env_utils import print_slurm_env


def setup_and_run_training():
    # Print SLURM environment
    print_slurm_env()

    # Setup the process group for distributed training based on SLURM environment variables
    rank = int(os.environ["SLURM_PROCID"])
    init_process_group(
        backend="nccl",
        init_method="env://",
        world_size=int(os.environ["SLURM_NTASKS"]),
        rank=rank,
        timeout=datetime.timedelta(seconds=60),  # <- You may need to tune this
    )
    device = torch.device(
        "cuda"  # <- Device ID is chosen based on ROCR_VISIBLE_DEVICES
    )

    torch.manual_seed(6021)
    train_kwargs = {
        "batch_size": 64,
        "num_workers": 7,
        "pin_memory": True,
    }
    test_kwargs = {
        "batch_size": 1000,
        "num_workers": 7,
        "pin_memory": True,
        "shuffle": True,
    }
    log_interval = 10
    epochs = 14
    learning_rate = 1.0
    gamma = 0.7

    model = DDP(Net().to(device))  # <- We need to wrap the model with DDP
    dataset_train, dataset_test, optimizer, scheduler = get_mnist_setup(
        model, learning_rate, gamma
    )
    train_loader = torch.utils.data.DataLoader(
        dataset_train,
        **train_kwargs,
        sampler=DistributedSampler(  # <- We need to use a DistributedSampler
            dataset_train
        ),
    )
    test_loader = torch.utils.data.DataLoader(dataset_test, **test_kwargs)

    t_start = time.perf_counter()
    for epoch in range(1, epochs + 1):
        train(log_interval, model, device, train_loader, optimizer, epoch, rank=rank)
        test(model, device, test_loader, epoch, rank=rank)
        scheduler.step()
    t_end = time.perf_counter()
    if rank == 0:
        print(f"Training time: {t_end - t_start:.2f} seconds")

    destroy_process_group()  # Cleanup the process group


if __name__ == "__main__":
    # Workaround "fork" not being safe with Slingshot 11 when using multiple
    # PyTorch DataLoader workers
    torch.multiprocessing.set_start_method("spawn")

    setup_and_run_training()
