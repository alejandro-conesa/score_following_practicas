import torch
from scf.model.spectrogram_cnn import CRNNSpectrogram

class Focus(torch.nn.Module):
    def forward(self, x):
        return torch.cat([
            x[..., 0::2, 0::2],
            x[..., 1::2, 0::2],
            x[..., 0::2, 1::2],
            x[..., 1::2, 1::2],
        ], dim=1)


class FocusBlock(torch.nn.Module):
    def __init__(self, in_channels=1, out_channels=16):
        super().__init__()
        self.focus = Focus()
        self.conv = torch.nn.Conv2d(in_channels*4, out_channels, kernel_size=3, padding=1)
        self.norm = torch.nn.LayerNorm([out_channels, 208, 208])
        self.activation = torch.nn.ELU(inplace=True)

    def forward(self, x):
        x = self.focus(x)
        x = self.conv(x)
        x = self.norm(x)
        x = self.activation(x)
        return x


class FiLM(torch.nn.Module):
    def __init__(self, out_channels, zdim=128): # la dimensión del vector z siempre es 128 a la entrada
        super().__init__()
        # gamma y beta para la film son capas nn.linear. mirar repo cyolo paper para dimensiones.
        self.gamma = torch.nn.Linear(zdim, out_channels)
        self.beta = torch.nn.Linear(zdim, out_channels)

    def forward(self, x, z):
        gamma = self.gamma(z).unsqueeze(-1).unsqueeze(-1)
        beta = self.beta(z).unsqueeze(-1).unsqueeze(-1)

        x = gamma * x + beta

        return x


class BottleneckBlock(torch.nn.Module):

    expansion = 1

    def __init__(self, inplanes, planes, out_dim, base_width=64):
        super().__init__()

        width = int(planes * (base_width / 64.))

        self.conv1 = torch.nn.Conv2d(inplanes, width, kernel_size=1, padding=0, stride=1, bias=False)
        self.ln1 = torch.nn.LayerNorm([width, out_dim, out_dim])
        self.conv2 = torch.nn.Conv2d(width, width, kernel_size=3, padding=1, stride=1, bias=False)
        self.ln2 = torch.nn.LayerNorm([width, out_dim, out_dim])
        self.conv3 = torch.nn.Conv2d(width, planes * self.expansion, kernel_size=1, padding=0, stride=1, bias=False)
        self.ln3 = torch.nn.LayerNorm([planes * self.expansion, out_dim, out_dim])

        self.activation = torch.nn.ELU(inplace=True)

        self.downsample = None
        if inplanes != planes:
            self.downsample = torch.nn.Sequential(
                torch.nn.Conv2d(inplanes, planes * self.expansion, kernel_size=1, stride=1, bias=False)
            )

    # downsample sacado del paper original casi idéntico
    def forward(self, x):
        identity = x

        out = self.conv1(x)
        out = self.ln1(out)
        out = self.activation(out)
        out = self.conv2(out)
        out = self.ln2(out)
        out = self.activation(out)
        out = self.conv3(out)
        out = self.ln3(out)

        if self.downsample is not None:
            identity = self.downsample(x)

        out += identity
        out = self.activation(out)
        return out
        

class UpscaleBlock(torch.nn.Module):
    def __init__(self, in_channels, out_channels, out_dim, film_active=False):
        super().__init__()
        self.conv = torch.nn.Conv2d(in_channels, out_channels, kernel_size=3, padding=1, stride=1)
        self.ln = torch.nn.LayerNorm([out_channels, out_dim, out_dim])
        self.activation = torch.nn.ELU(inplace=True)
        self.upsample = torch.nn.Upsample(scale_factor=2, mode="nearest")
        self.bottleneck = BottleneckBlock(in_channels*2, out_channels, out_dim=out_dim)

        if film_active:
            self.film = FiLM(out_channels, out_channels)
        else:
            self.film = None

    def forward(self, x, z=None, res=None):
        x = self.conv(x)
        x = self.ln(x)
        if self.film:
            x = self.film(x, z)
        x = self.activation(x)
        if res is not None:
            x = torch.cat((x, res), dim=1)
        x = self.bottleneck(x)
        return x


class DownscaleBlock(torch.nn.Module):
    def __init__(self, in_channels, out_channels, out_dim, film_active=False):
        super().__init__()
        self.conv = torch.nn.Conv2d(in_channels, out_channels, kernel_size=3, padding=1, stride=2)
        self.ln = torch.nn.LayerNorm([out_channels, out_dim, out_dim])
        self.activation = torch.nn.ELU(inplace=True)
        self.bottleneck = BottleneckBlock(out_channels, out_channels, out_dim=out_dim)

        if film_active:
            self.film = FiLM(out_channels, out_channels)
        else:
            self.film = None

    def forward(self, x, z=None):
        x = self.conv(x)
        x = self.ln(x)
        if self.film:
            x = self.film(x, z)
        x = self.activation(x)
        x = self.bottleneck(x)
        return x


class cyoloSCF(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.audio_encoder = CRNNSpectrogram()