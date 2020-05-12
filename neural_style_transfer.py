# -*- coding: utf-8 -*-
"""neural_style_transfer.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/13NUwlJzQAxBOS9oJxbcgIW_vNhuruZXo
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim

from PIL import Image
import matplotlib.pyplot as plt

import torchvision.transforms as transforms
import torchvision.models as models

import copy
import numpy as np

#detect is there cuda available for GPU training 
#otherwise it will use CPU
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

#load image by name
#resize the image and convert it to tensor
def image_loader(image_name, imsize):
	loader = transforms.Compose([transforms.Resize(imsize),
								 transforms.ToTensor()])
	image = Image.open(image_name) #read the image as [C, H, W]
	image = loader(image).unsqueeze(0) #put in a batch dimension in front for training purpose [1, C, H, W]

	return image.to(device, torch.float)

#display tensor as image
def imshow(tensor, title=None):
	#convert tensor to image
	unloader = transforms.ToPILImage()
	#clone the tensor so that we wont make change to the original tensor
	image = tensor.cpu().clone() 
	image = image.squeeze(0) # remove the batch dimension
	image = unloader(image)

	plt.imshow(image)
	if title is not None:
		plt.title(title)
	plt.pause(1)

#gram matrix for style loss
def gram_matrix(input):
	b, c, h, w = input.size()
	#b = batch = 1
	#c = channel of image
	#h = height, w=width

	features = input.view(b*c, h*w) #resize it to [c, h*w]

	G = torch.mm(features, features.t()) #gram matrix between features and the transposed ver

	#normalize the gram matrix 
	#by dividing the number of element in each feature maps
	return G.div(b*c*h*w)

#Content Loss
class ContentLoss(nn.Module):
	def __init__(self, target):
		super(ContentLoss, self).__init__()
		self.target = target.detach() #detach is used when you want to compute something that you dont want to differentiate

	def forward(self, input):
		self.loss = F.mse_loss(input, self.target) #compute mse loss between features of content image(self.target) and generated image(input)
		return input

#Style Loss
class StyleLoss(nn.Module):
	def __init__(self, target_features):
		super(StyleLoss, self).__init__()
		self.target = gram_matrix(target_features).detach()

	def forward(self, input):
		G = gram_matrix(input)
		self.loss = F.mse_loss(G, self.target)
		return input

#create module to normalize the input image so we can put it in nn.Sequentiol
class Normalization(nn.Module):
	def __init__(self, mean, std):
		super(Normalization, self).__init__()
		#reshape mean and std to [C, 1, 1] so they can
		#work directly with image tensor of shape [B x C x H x W]
		self.mean = torch.tensor(mean).view(-1, 1, 1) 
		self.std = torch.tensor(std).view(-1, 1, 1)

	def forward(self, img):
		#normalize the input image
		return (img - self.mean) / self.std

def get_style_model_and_losses(cnn, normalization_mean, normalization_std,
								style_img, content_img, 
								content_layers, style_layers):
	cnn = copy.deepcopy(cnn)

	#normalization module
	normalization = Normalization(normalization_mean, normalization_std).to(device)

	#save the content and style losses layer
	content_losses = []
	style_losses = []

	#assume the cnn is nn.Sequential, we make a new nn.Sequential
	#to put in modules that are supposed to be activated sequentially
	model = nn.Sequential(normalization)

	#name the layers
	block, i = 1, 1
	for layer in cnn.children():
		if isinstance(layer, nn.Conv2d):
			name = "conv{}_{}".format(block, i)
		elif isinstance(layer, nn.ReLU):
			name = "relu{}_{}".format(block, i)
			layer = nn.ReLU(inplace=False)
			i += 1
		elif isinstance(layer, nn.MaxPool2d): 
			name = "pool{}_{}".format(block, i)
			block += 1
			i = 1
		else:
			raise RuntimeError('Unrecognized layer: {}'.format(layer.__class__.__name__))

		model.add_module(name, layer)

		if name in content_layers:
			target = model(content_img).detach()
			content_loss = ContentLoss(target)
			model.add_module("content_loss{}_{}".format(block, i), content_loss)
			content_losses.append(content_loss)

		if name in style_layers:
			target_features = model(style_img).detach()
			style_loss = StyleLoss(target_features)
			model.add_module("style_loss{}_{}".format(block, i), style_loss)
			style_losses.append(style_loss)

	#cut of later layers that we didnt use
	for i in range(len(model)-1, -1, -1):
		if isinstance(model[i], ContentLoss) or isinstance(model[i], StyleLoss):
			break
	model = model[:(i+1)]

	return model, style_losses, content_losses

def get_input_optimizer(input_image):
	# input image is a parameter that requires gradient, will change the input image
	optimizer = optim.LBFGS([input_image.requires_grad_()])
	return optimizer

def run_style_transfer(model, style_losses, content_losses,
						content_image, style_image, input_image,
						num_steps, style_weight=1000000, content_weight=1):
	print('Building the style transfer model..')
	optimizer = get_input_optimizer(input_image)

	#save images from each 50 iterations
	output_images = []

	print('Optimizing..')
	run = [0]
	while run[0] <= num_steps:

		def closure():
			#update the input image
			input_image.data.clamp_(0, 1)

			optimizer.zero_grad()
			model(input_image) #insert input image into model

			style_score = 0 
			content_score = 0

			for sl in style_losses:
				style_score += (1/5)*sl.loss
			for cl in content_losses:
				content_score += cl.loss

			style_score = style_weight * style_score
			content_score = content_weight * content_score

			loss = style_score + content_score
			loss.backward()

			#print out loss every 50 iterations
			run[0] += 1
			if run[0] % 50 == 0:
				print("run {}:".format(run))
				print('Style Loss : {:4f} Content Loss: {:4f}'.format(style_score.item(), content_score.item()))
				output_images.append(input_image.cpu().clone())
				imshow(input_image)
				print()

			return style_score + content_score

		optimizer.step(closure)

	#last update of input image
	input_image.data.clamp_(0, 1)

	return output_images

#Variable initialization
#desired layers for content and style loss
content_layers_default = ['conv3_1']
style_layers_default = ['conv1_1', 'conv2_1', 'conv3_1', 'conv4_1', 'conv5_1']
num_steps = 2000

#import vgg19 model (here we set it to evaluation mode)
cnn = models.vgg19(pretrained=True).features.to(device).eval()

#VGG network are normalized with special values for mean and std
cnn_normalization_mean = torch.tensor([0.485, 0.456, 0.406]).to(device)
cnn_normalization_std = torch.tensor([0.229, 0.224, 0.225]).to(device)

#size of images for GPU/CPU training
#loading of images
imsize = 512 if torch.cuda.is_available() else 256
style_image = image_loader("style4.jpeg", imsize)
content_image = image_loader("content7.jpg", imsize)
input_image = torch.randn(content_image.data.size(), device=device) #random noise

#error checking
assert style_image.size() == content_image.size(), "The size of style and content images have to be the same!"

#interactive plot
plt.ion()

#show images for training
plt.figure()
imshow(style_image, "Style image")

plt.figure()
imshow(content_image, "Content image")

plt.figure()

imshow(input_image, "Input image")

#get our own renamed model and losses that we needed
model, style_losses, content_losses = get_style_model_and_losses(cnn, cnn_normalization_mean, cnn_normalization_std,
																style_image, content_image, 
																content_layers_default, style_layers_default)

#optimizing the image
output_images = run_style_transfer(model, style_losses, content_losses,
							                              content_image, style_image, input_image,
						                              	num_steps, style_weight=1000000, content_weight=1)

plt.figure(figsize=(10,10))
imshow(output_images[-1])

unloader = transforms.ToPILImage()
output_image = output_images[-1].cpu().clone()
output_image = output_image.squeeze(0)
output_image = unloader(output_image)

output_image.save("output742.png")
