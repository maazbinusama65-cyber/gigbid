import torch
from torch import nn

def check_clinical(model, loader, opt):
    model.train()
    for x, y in loader:
        opt.zero_grad()
        loss = nn.functional.cross_entropy(model(x), y)
        loss.backward()
        opt.step()
