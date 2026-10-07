import torch

# entrada a la red imagen (78 x frames) 
# prueba con (78 x 40)

# input (B, T, 1, 78, 40) asumimos T=1 primera iteración
# ver si cambiar input a (B, 1, 78, x) con spectrogram completo
# unfold, añadir padding

class CRNNSpectrogram(torch.nn.Module):
    def __init__(self):
        super.__init__()
        self.bn = torch.nn.BatchNorm2d(1)

        self.conv1_24 = torch.nn.Conv2d(1, 24, 3, 1, 1) 
        self.conv24_24 = torch.nn.Conv2d(24, 24, 3, 1, 1)
        self.ln1 = torch.nn.LayerNorm([24, 78, 40]) # salen del maxpool 39, 20

        self.conv24_48 = torch.nn.Conv2d(24, 48, 3, 1, 1)
        self.conv48_48 = torch.nn.Conv2d(48, 48, 3, 1, 1)
        self.ln2 = torch.nn.LayerNorm([48, 39, 20]) # salen del maxpool 19, 10

        self.conv48_96 = torch.nn.Conv2d(48, 48, 3, 1, 1)
        self.conv96_96 = torch.nn.Conv2d(96, 96, 3, 1, 1)
        self.ln3 = torch.nn.LayerNorm([96, 19, 10]) # salen del maxpool 9, 5
        self.ln4 = torch.nn.LayerNorm([96, 9, 5])

        self.final_conv = torch.nn.Conv2d(96, 96, 1, 1, 0)
        self.ln_final = torch.nn.LayerNorm([96, 4, 2])

        self.dense = torch.nn.Linear(768, 32)

        self.lstm = torch.nn.LSTM(input_size=32, hidden_size=64, num_layers=1, batch_first=True)

        self.dense2 = torch.nn.Linear(96, 128)
        self.ln_dense2 = torch.nn.LayerNorm([128])

        self.maxpool = torch.nn.MaxPool2d(kernel_size=2)
        self.elu = torch.nn.ELU()

    def forward(self, x):
        x = self.bn(x)

        x = self.conv1_24(x)
        x = self.ln1(x)
        x = self.elu(x)
        x = self.conv24_24(x)
        x = self.ln1(x)
        x = self.elu(x)
        x = self.maxpool(x)

        x = self.conv24_48(x)
        x = self.ln2(x)
        x = self.elu(x)
        x = self.conv48_48(x)
        x = self.ln2(x)
        x = self.elu(x)
        x = self.maxpool(x)

        x = self.conv48_96(x)
        x = self.ln3(x)
        x = self.elu(x)
        x = self.conv96_96(x)
        x = self.ln3(x)
        x = self.elu(x)
        x = self.maxpool(x)

        x = self.conv96_96(x)
        x = self.ln3(x)
        x = self.elu(x)
        x = self.conv96_96(x)
        x = self.ln3(x)
        x = self.elu(x)
        x = self.maxpool(x)

        x = self.final_conv(x)
        x = self.ln_final(x)
        x = self.elu(x)

        x = x.flatten(start_dim=1)

        x = self.dense(x)

        x, hidden = self.lstm(x)

        z = torch.cat([hidden, x])

        z = self.dense2(z)
        z = self.ln_dense2(z)
        z = self.elu(z)

        return z


