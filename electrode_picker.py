#!/usr/env/python
import matplotlib
matplotlib.use('Qt4Agg') 
from matplotlib import pyplot as plt
plt.rcParams['keymap.save'] = '' # Unbind 's' key saving
from matplotlib import cm
import matplotlib.colors as mcolors
import numpy as np
import nibabel as nib
import scipy.ndimage
import sys
from PyQt4 import QtCore, QtGui
import matplotlib.patches as mpatches
import scipy.io
import os

class electrode_picker:
	'''
	electrode_picker class
	'''
	def __init__(self, subj_dir):
		'''
		Initialize the electrode picker with the user-defined MRI and co-registered
		CT scan in [subj_dir].  Images will be displayed using orientation information 
		obtained from the image header. Images will be resampled to dimensions 
		[256,256,256] for display.
		We will also listen for keyboard and mouse events so the user can interact
		with each of the subplot panels (zoom/pan) and add/remove electrodes with a 
		keystroke.
		'''
		QtCore.pyqtRemoveInputHook()
		self.subj_dir = subj_dir
		self.img = nib.load(os.path.join(subj_dir, 'mri', 'brain.mgz'))
		self.ct = nib.load(os.path.join(subj_dir, 'CT', 'rCT.nii'))
		self.affine = self.img.affine
		self.fsVox2RAS = np.array([[-1., 0., 0., 128.], 
								   [0., 0., 1., -128.], 
								   [0., -1., 0., 128.], 
								   [0., 0., 0., 1.]])

		# Apply orientation to the MRI so that the order of the dimensions will be
		# sagittal, coronal, axial
		self.codes = nib.orientations.axcodes2ornt(nib.orientations.aff2axcodes(self.affine))
		img_data = nib.orientations.apply_orientation(self.img.get_data(), self.codes)
		self.voxel_sizes = nib.affines.voxel_sizes(self.affine)
		nx,ny,nz = np.array(img_data.shape, dtype='float')

		self.inv_affine = np.linalg.inv(self.affine)
		self.img_clim = np.percentile(img_data, (1., 99.))

		# Apply orientation to the CT so that the order of the dimensions will be
		# sagittal, coronal, axial
		self.ct_codes =nib.orientations.axcodes2ornt(nib.orientations.aff2axcodes(self.ct.affine))
		ct_data = nib.orientations.apply_orientation(self.ct.get_data(), self.ct_codes)

		# Threshold the CT so only bright objects (electrodes) are visible
		ct_data[ct_data < 1000] = np.nan
		cx,cy,cz=np.array(self.ct.shape, dtype='float')
		

		# Resample both images to the highest resolution
		voxsz = (256, 256, 256)
		if self.ct.shape != voxsz:
			print("Resizing voxels in CT")
			ct_data = scipy.ndimage.zoom(ct_data, [voxsz[0]/cx, voxsz[1]/cy, voxsz[2]/cz])
		if self.img.shape != voxsz:
			print("Resizing voxels in MRI")
			img_data = scipy.ndimage.zoom(img_data, [voxsz[0]/nx, voxsz[1]/ny, voxsz[2]/nz])
		
		self.ct_data = ct_data
		self.img_data = img_data
		self.elec_data = np.nan+np.zeros((img_data.shape))
		self.bin_mat = '' # binary mask for electrodes
		self.device_num = 0 # Start with device 0, increment when we add a new electrode name type
		self.device_name = ''
		self.devices = [] # This will be a list of the devices (grids, strips, depths)
		self.elec_num = dict()
		self.elecmatrix = dict()# This will be the electrode coordinates 
		self.legend_handles = [] # This will hold legend entries

		self.imsz = [256, 256, 256]
		self.ctsz = [256, 256, 256]

		self.current_slice = np.array([self.imsz[0]/2, self.imsz[1]/2, self.imsz[2]/2], dtype=np.float)
		
		self.fig=plt.figure(figsize=(12,10))
		#thismanager = plt.get_current_fig_manager()
		#thismanager.window.setWindowIcon(QtGui.QIcon('/Users/liberty/Downloads/leftbrain_DyBkFr.ico'))
		
		self.im = []
		self.ct_im = []
		self.elec_im = []

		self.cursor = []
		self.cursor2 = []

		im_ranges = [[0, self.imsz[1], 0, self.imsz[2]],
					 [0, self.imsz[0], 0, self.imsz[2]],
					 [0, self.imsz[0], 0, self.imsz[1]]]
		im_labels = [['Inferior','Posterior'],
					 ['Inferior','Left'],
					 ['Posterior','Left']]

		self.ax = []
		
		# This is the current slice for indexing (as integers so python doesnt complain)
		cs = np.round(self.current_slice).astype(np.int)

		# Plot sagittal, coronal, and axial views 
		for i in np.arange(3):
			self.ax.append(self.fig.add_subplot(2,2,i+1))
			self.ax[i].set_axis_bgcolor('k')
			if i==0:
				imdata = img_data[cs[0],:,:].T
				ctdat = ct_data[cs[0],:,:].T
				edat = self.elec_data[cs[0],:,:].T
			elif i==1:
				imdata = img_data[:,cs[1],:].T
				ctdat = ct_data[:,cs[1],:].T
				edat = self.elec_data[:,cs[1],:].T
			elif i==2:
				imdata = img_data[:,:,cs[2]].T
				ctdat = ct_data[:,:,cs[2]].T
				edat = self.elec_data[:,:,cs[2]].T

			# Show the MRI data in grayscale
			self.im.append(plt.imshow(imdata, cmap=cm.gray, aspect='auto'))

			# Overlay the CT on top in "hot" colormap, slightly transparent
			self.ct_im.append(plt.imshow(ctdat, cmap=cm.hot, aspect='auto',alpha=0.5, vmin=1000, vmax=3000))
			
			# Overlay the electrodes image on top (starts as NaNs, is eventually filled in)
			self.elec_colors = mcolors.LinearSegmentedColormap.from_list('elec_colors', np.vstack (( cm.Set1(np.linspace(0., 1, 9)), cm.Set2(np.linspace(0., 1, 8)) )) )
			self.elec_im.append(plt.imshow(edat, cmap=self.elec_colors, aspect='auto', alpha=1, vmin=0, vmax=17))
			
			# Plot a green cursor
			self.cursor.append(plt.plot([cs[1], cs[1]], [self.ax[i].get_ylim()[0]+1, self.ax[i].get_ylim()[1]-1], color=[0, 1, 0] ))
			self.cursor2.append(plt.plot([self.ax[i].get_xlim()[0]+1, self.ax[i].get_xlim()[1]-1], [cs[2], cs[2]], color=[0, 1, 0] ))
			
			# Flip the y axis so brains are the correct side up
			plt.gca().invert_yaxis()

			# Get rid of tick labels
			self.ax[i].set_xticks([])
			self.ax[i].set_yticks([])

			# Label the axes
			self.ax[i].set_xlabel(im_labels[i][0])
			self.ax[i].set_ylabel(im_labels[i][1])
			self.ax[i].axis(im_ranges[i])

		# Plot the maximum intensity projection
		self.ct_slice = 's' # Show sagittal MIP to start
		self.ax.append(self.fig.add_subplot(2,2,4))
		self.ax[3].set_axis_bgcolor('k')
		self.im.append(plt.imshow(np.nanmax(ct_data[cs[0]-50:cs[0]-20,:,:], axis=0).T, cmap=cm.gray, aspect='auto'))
		self.cursor.append(plt.plot([cs[1], cs[1]], [self.ax[3].get_ylim()[0]+1, self.ax[3].get_ylim()[1]-1], color=[0, 1, 0] ))
		self.cursor2.append(plt.plot([self.ax[3].get_xlim()[0]+1, self.ax[3].get_xlim()[1]-1], [cs[2], cs[2]], color=[0, 1, 0] ))
		self.ax[3].set_xticks([])
		self.ax[3].set_yticks([])
		plt.gca().invert_yaxis()
		self.ax[3].axis([0,self.imsz[1],0,self.imsz[2]])

		self.elec_im.append(plt.imshow(self.elec_data[cs[0],:,:].T, cmap=self.elec_colors, aspect='auto', alpha=1, vmin=0, vmax=17))
		plt.gcf().suptitle("Press 'n' to enter device name in console, press 'e' to add an electrode at crosshair, press 'h' for more options", fontsize=14)

		plt.tight_layout()
		plt.subplots_adjust(top=0.9)
		cid2 = self.fig.canvas.mpl_connect('scroll_event',self.on_scroll)
		cid3 = self.fig.canvas.mpl_connect('button_press_event',self.on_click)
		cid = self.fig.canvas.mpl_connect('key_press_event', self.on_key)
		#cid4 = self.fig.canvas.mpl_connect('key_release_event', self.on_key)

		plt.show()
		self.fig.canvas.draw()

	def on_key(self, event):
		''' 
		Executes when the user presses a key.  Potential key inputs are:

		Electrode adding:
		----
		n: enter the name of a new device (e.g. 'frontalgrid','hippocampaldepth')
		e: insert an electrode at the current green crosshair position
		u: remove electrode at the current crosshair position (can be thought of like "undo")

		Views:
		----
		s: sagittal view for maximum intensity projection at bottom right
		c: coronal view for maximum intensity projection at bottom right
		a: axial view for maximum intensity projection at bottom right
		pagedown/pageup: move by one slice in currently selected pane
		arrow up/arrow down: pan by one voxel in currently selected pane
		'''
		#print('You pressed', event.key)
		bb1=self.ax[0].get_position()
		bb2=self.ax[1].get_position()
		bb3=self.ax[2].get_position()
		bb4=self.ax[3].get_position()

		# Transform coordinates to figure coordinates
		fxy = self.fig.transFigure.inverted().transform((event.x, event.y))
		#print event.x, event.y
		#print self.current_slice

		slice_num = []
		if bb1.contains(fxy[0],fxy[1]):
			slice_num = 0
		if bb2.contains(fxy[0],fxy[1]):
			slice_num = 1
		if bb3.contains(fxy[0],fxy[1]):
			slice_num = 2
		if bb4.contains(fxy[0],fxy[1]):
			slice_num = 3

		if slice_num != []:
			this_ax = self.ax[slice_num]

			if event.key == 'escape':
				plt.close()
			if event.key == 'n':
				plt.gcf().suptitle("Enter electrode name in python console", fontsize=14)
				self.device_name = raw_input("Enter electrode name: ")
				#plt.gcf().canvas.draw()

				# If the device name is not in the list
				if self.device_name not in self.devices:
					self.devices.append(self.device_name)
					self.device_num = np.max(self.device_num)+1 # Find the next number 
				else:
					self.device_num = self.devices.index(self.device_name)
				
				plt.gcf().suptitle("Click on electrodes for device number %d, %s"%(self.device_num, self.device_name), fontsize=14)

				# If the device name is not in the list, start with electrode 0, or
				# load the electrode file if it exists and start with the next number
				# electrode
				if self.device_name not in self.elec_num:
					self.elec_num[self.device_name] = 0
					elecfile = os.path.join(self.subj_dir, 'elecs', self.device_name+'.mat')
					if os.path.isfile(elecfile):
						emat = scipy.io.loadmat(elecfile)['elecmatrix']
						self.elecmatrix[self.device_name] = list(emat)
						print("Loading %s (if you wish to overwrite, remove this file before running)"%(elecfile))
						for elec in emat:
							self.current_slice = self.surfaceRAS_to_slice(elec[:3])
							self.add_electrode(add_to_file=False)
						print("Starting to mark electrode %d"%(self.elec_num[self.device_name]))
				self.update_legend()

			if event.key == 'h':
				# Show help 
				plt.gcf().suptitle("Help: 'n': name device, 'e': add electrode, 'u': remove electrode\nMaximum intensity projection views: 's': sagittal, 'c': coronal, 'a': axial\n\Scroll to zoom, arrows to pan, pgup/pgdown or click to go to slice", fontsize=12)

			if event.key == 'e':
				if self.device_name == '':
					plt.gcf().suptitle("Please name device with 'n' key before selecting electrode with 'e'", color='r', fontsize=14)
				else:
					self.add_electrode()

			if event.key == 'u':
				self.remove_electrode()

			# Maximum intensity projection in another dimension
			ct_slice = dict()
			ct_slice['s'] = 0
			ct_slice['c'] = 1
			ct_slice['a'] = 2
			if event.key == 's' or event.key == 'c' or event.key == 'a':
				self.ct_slice = event.key

			# Scrolling through slices
			if event.key == 'pageup' or event.key == 'pagedown':
				if event.key == 'pagedown':
					sgn = -1
				else:
					sgn = 1
				if slice_num < 3:
					self.current_slice[slice_num] = self.current_slice[slice_num] + 1*sgn
				if slice_num == 3:
					self.current_slice[ct_slice[self.ct_slice]] = self.current_slice[ct_slice[self.ct_slice]] + 1*sgn

			# Panning left/right/up/down
			if event.key == 'up' or event.key == 'down' or event.key == 'left' or event.key == 'right':
				if event.key == 'up' or event.key == 'down':
					if event.key == 'up':
						sgn = -1
					else:
						sgn = 1
					ylims = this_ax.get_ylim()
					this_ax.set_ylim([ylims[0]+1*sgn, ylims[1]+1*sgn])
					
				elif event.key == 'left' or event.key == 'right':
					if event.key == 'right':
						sgn = -1
					else:
						sgn = 1
					xlims = this_ax.get_xlim()
					this_ax.set_xlim([xlims[0]+1*sgn, xlims[1]+1*sgn])

			# Draw the figure
			self.update_figure_data()
			plt.gcf().canvas.draw()

	def on_scroll(self, event):
		''' Use mouse scroll wheel to zoom.  Scroll down zooms in, scroll up zooms out.
		'''
		stepsz = 10.
		bb1=self.ax[0].get_position()
		bb2=self.ax[1].get_position()
		bb3=self.ax[2].get_position()
		bb4=self.ax[3].get_position()

		# Transform coordinates to figure coordinates
		fxy = self.fig.transFigure.inverted().transform((event.x, event.y))
		
		# Find which subplot had the mouse focus
		if bb1.contains(fxy[0],fxy[1]):
			this_ax = self.ax[0]
			x = self.current_slice[1]
			y = self.current_slice[2]
		if bb2.contains(fxy[0],fxy[1]):
			this_ax = self.ax[1]
			x = self.current_slice[0]
			y = self.current_slice[2]
		if bb3.contains(fxy[0],fxy[1]):
			this_ax = self.ax[2]
			x = self.current_slice[0]
			y = self.current_slice[1]
		if bb4.contains(fxy[0],fxy[1]):
			this_ax = self.ax[3]
			x = self.current_slice[1]
			y = self.current_slice[2]

		xlims = this_ax.get_xlim()
		ylims = this_ax.get_ylim()

		xstep = event.step*stepsz
		ystep = event.step*stepsz

		if x > xlims[0] and x < xlims[1]:
			xratio = np.abs(xlims[1]-x)/np.abs(xlims[0]-x)
		else:
			xratio = 0.5
		if y > ylims[0] and y < ylims[1]:
			yratio = np.abs(ylims[1]-y)/np.abs(ylims[0]-y)
		else:
			yratio = 0.5

		xratio = 0.5
		yratio = 0.5

		this_ax.set_xlim(xlims[0]+xstep*2*(1-xratio), xlims[1] - xstep*2*(xratio))
		this_ax.set_ylim(ylims[0]+ystep*2*(1-yratio), ylims[1] - ystep*2*(yratio))

		plt.gcf().canvas.draw()

	def on_click(self, event):
		'''
		Executes on mouse click events -- moves appropriate subplot axes to (x,y,z)
		view on MRI and CT views.
		'''

		#print('You scrolled %d steps at x: %d, y: %d', event.step, event.x, event.y)
		# Get the bounding box for each of the subplots
		bb1=self.ax[0].get_position()
		bb2=self.ax[1].get_position()
		bb3=self.ax[2].get_position()
		bb4=self.ax[3].get_position()

		#print event.xdata, event.ydata
		# Transform coordinates to figure coordinates
		fxy = self.fig.transFigure.inverted().transform((event.x, event.y))
		
		x = np.int(np.round(event.xdata))
		y = np.int(np.round(event.ydata))

		# If you clicked the first subplot
		if bb1.contains(fxy[0],fxy[1]):
			self.current_slice[1] = event.xdata
			self.current_slice[2] = event.ydata
			
		# If you clicked the second subplot
		elif bb2.contains(fxy[0],fxy[1]):
			self.current_slice[0] = event.xdata
			self.current_slice[2] = event.ydata

		# If you clicked the third subplot
		elif bb3.contains(fxy[0],fxy[1]):
			self.current_slice[0] = event.xdata
			self.current_slice[1] = event.ydata

		# If you clicked the third subplot
		elif bb4.contains(fxy[0],fxy[1]):
			if self.ct_slice == 's':
				self.current_slice[1] = event.xdata
				self.current_slice[2] = event.ydata
			elif self.ct_slice == 'c':
				self.current_slice[0] = event.xdata
				self.current_slice[2] = event.ydata
			elif self.ct_slice == 'a':
				self.current_slice[0] = event.xdata
				self.current_slice[1] = event.ydata
		
		self.update_figure_data()

		#print("Current slice: %3.2f %3.2f %3.2f"%(self.current_slice[0], self.current_slice[1], self.current_slice[2]))
		plt.gcf().canvas.draw()

	def update_figure_data(self):
		'''
		Updates all four subplots based on the crosshair position (self.current_slice)
		'''
		cs = np.round(self.current_slice).astype(np.int) # Make integer for indexing the volume
		self.im[0].set_data(self.img_data[cs[0],:,:].T)
		self.im[1].set_data(self.img_data[:,cs[1],:].T)
		self.im[2].set_data(self.img_data[:,:,cs[2]].T)

		if self.ct_slice == 's':
			self.im[3].set_data(np.nanmax(self.ct_data[cs[0]-15:cs[0]+15,:,:], axis=0).T)
		elif self.ct_slice == 'c':
			self.im[3].set_data(np.nanmax(self.ct_data[:,cs[1]-15:cs[1]+15,:], axis=1).T)
		elif self.ct_slice == 'a':
			self.im[3].set_data(np.nanmax(self.ct_data[:,:,cs[2]-15:cs[2]+15], axis=2).T)


		self.ct_im[0].set_data(self.ct_data[cs[0],:,:].T)
		self.ct_im[1].set_data(self.ct_data[:,cs[1],:].T)
		self.ct_im[2].set_data(self.ct_data[:,:,cs[2]].T)

		self.elec_im[0].set_data(self.elec_data[cs[0],:,:].T)
		self.elec_im[1].set_data(self.elec_data[:,cs[1],:].T)
		self.elec_im[2].set_data(self.elec_data[:,:,cs[2]].T)
		if self.ct_slice == 's':
			self.elec_im[3].set_data(self.elec_data[cs[0],:,:].T)
			self.cursor[3][0].set_xdata ([self.current_slice[1], self.current_slice[1]]) 
			self.cursor2[3][0].set_ydata([self.current_slice[2], self.current_slice[2]])

		elif self.ct_slice == 'c':
			self.elec_im[3].set_data(self.elec_data[:,cs[1],:].T)
			self.cursor[3][0].set_xdata ([self.current_slice[0], self.current_slice[0]]) 
			self.cursor2[3][0].set_ydata([self.current_slice[2], self.current_slice[2]])
		elif self.ct_slice == 'a':
			self.elec_im[3].set_data(self.elec_data[:,:,cs[2]].T)
			self.cursor[3][0].set_xdata ([self.current_slice[0], self.current_slice[0]]) 
			self.cursor2[3][0].set_ydata([self.current_slice[1], self.current_slice[1]])

		self.cursor[0][0].set_xdata ([self.current_slice[1], self.current_slice[1]]) 
		self.cursor2[0][0].set_ydata([self.current_slice[2], self.current_slice[2]])
		self.cursor[1][0].set_xdata ([self.current_slice[0], self.current_slice[0]])
		self.cursor2[1][0].set_ydata([self.current_slice[2], self.current_slice[2]])
		self.cursor[2][0].set_xdata ([self.current_slice[0], self.current_slice[0]])
		self.cursor2[2][0].set_ydata([self.current_slice[1], self.current_slice[1]])

	def add_electrode(self, add_to_file = True):
		'''
		Add an electrode at the current crosshair point. 
		'''
		cs = np.round(self.current_slice).astype(np.int) # Make integer for indexing the volume

		# create a sphere centered around the current point as a binary matrix
		radius = 2
		r2 = np.arange(-radius, radius+1)**2
		dist2 = r2[:,None,None]+r2[:,None]+r2
		bin_mat = np.array(dist2<=radius**2, dtype=np.float)
		bin_mat[bin_mat==0] = np.nan
		# The sphere part of the binary matrix will have a value that
		# increments with device number so that different devices
		# wil show up in different colors
		bin_mat = bin_mat+self.device_num-2
		self.bin_mat = bin_mat
		
		# Set the electrode data volume for this bounding box (add the
		# sphere to the electrode "volume" so it shows up in the brain
		# plots)
		self.elec_data[cs[0]-radius:cs[0]+radius+1, cs[1]-radius:cs[1]+radius+1, cs[2]-radius:cs[2]+radius+1] = bin_mat

		self.elec_im[0].set_data(self.elec_data[cs[0],:,:].T)
		self.elec_im[0].set_data(self.elec_data[:,cs[1],:].T)
		self.elec_im[0].set_data(self.elec_data[:,:,cs[2]].T)

		# As displayed, these coordinates are LSP, and we want RAS,
		# so we do that here

		elec = self.slice_to_surfaceRAS()

		if self.device_name not in self.elecmatrix:
			# Initialize the electrode matrix
			self.elecmatrix[self.device_name] = []
		self.elecmatrix[self.device_name].append(elec)

		if add_to_file:
			elecfile = os.path.join(self.subj_dir, 'elecs', self.device_name+'.mat')
			scipy.io.savemat(elecfile, {'elecmatrix': np.array(self.elecmatrix[self.device_name])})

		plt.gcf().suptitle('%s e%d surface RAS = [%3.3f, %3.3f, %3.3f]'%(self.device_name, self.elec_num[self.device_name], elec[0], elec[1], elec[2]), fontsize=14)
		
		self.elec_num[self.device_name] += 1
		#print("Voxel CRS: %3.3f, %3.3f, %3.3f"%(self.current_slice[0], self.current_slice[1], self.current_slice[2]))
		#print("RAS coordinate: %3.3f, %3.3f, %3.3f"%(elec[0], elec[1], elec[2]))

	def remove_electrode(self):
		'''
		Remove the electrode at the current crosshair point. 
		'''
		cs = self.current_slice
		if self.bin_mat != '':
			self.bin_mat = ''
			
			# Remove the electrode from elecmatrix
			self.elecmatrix[self.device_name].pop()

			# Save the electrode matrix
			elecfile = os.path.join(self.subj_dir, 'elecs', self.device_name+'.mat')
			scipy.io.savemat(elecfile, {'elecmatrix': np.array(self.elecmatrix[self.device_name])})

			# Remove the electrode from the volume display
			self.elec_data[cs[0]-radius:cs[0]+radius+1, cs[1]-radius:cs[1]+radius+1, cs[2]-radius:cs[2]+radius+1] = np.nan

			self.elec_im[0].set_data(self.elec_data[cs[0],:,:].T)
			self.elec_im[0].set_data(self.elec_data[:,cs[1],:].T)
			self.elec_im[0].set_data(self.elec_data[:,:,cs[2]].T)

	def slice_to_surfaceRAS(self, coord = None):
		'''
		Convert slice coordinate from the viewer to surface RAS
		'''
		if coord is None:
			coord = self.current_slice

		elec_CRS = np.hstack((self.imsz[0] - coord[0],
							  self.imsz[2] - coord[2],
							  coord[1], 1))
		
		# Convert CRS to RAS
		elec = np.dot(self.fsVox2RAS, elec_CRS.transpose()).transpose()
		elec = elec[:3]

		return elec

	def surfaceRAS_to_slice(self, elec):
		'''
		Convert surface RAS to coordinate to be used in the viewer
		'''
		elec = np.hstack((elec, 1))

		# Convert CRS to RAS
		elec_CRS = np.dot(np.linalg.inv(self.fsVox2RAS), elec.transpose()).transpose()

		print(elec_CRS)
		coord = np.hstack((elec_CRS[0],
						   elec_CRS[2],
						   self.imsz[1] - elec_CRS[1]))
		
		return coord

	def update_legend(self):
		self.legend_handles = []
		for i in self.devices:
			QtCore.pyqtRemoveInputHook()
			cmap = self.elec_colors
			num = self.devices.index(i)
			print("%s is number %d"%(i, num))
			c = cmap(num/17.)
			#print("Color: ")
			#print(c)
			color_patch = mpatches.Patch(color=c, label=i)
			self.legend_handles.append(color_patch)
			plt.legend(handles=self.legend_handles, loc='upper right', fontsize='x-small')
			#plt.legend(handles = [color_patch])
			#plt.show()
			
if __name__ == '__main__':
	app = QtGui.QApplication([])
	app.setWindowIcon(QtGui.QIcon(os.path.join('icons','leftbrain.png')))
	subj_dir = sys.argv[1]
	e = electrode_picker(subj_dir = subj_dir)