#main.py from py3dbp
from .constants import RotationType, Axis
from .auxiliary_methods import intersect, set2Decimal
import numpy as np
# required to plot a representation of Bin and contained items 
from matplotlib.patches import Rectangle,Circle
import matplotlib.pyplot as plt
import mpl_toolkits.mplot3d.art3d as art3d
from collections import Counter
import copy
DEFAULT_NUMBER_OF_DECIMALS = 0
START_POSITION = [0, 0, 0]



class Item:

    def __init__(self, partno,name,typeof, WHD, weight, level, loadbear, updown, color):
        ''' '''
        self.partno = partno
        self.name = name
        self.typeof = typeof
        self.width = WHD[0]
        self.height = WHD[1]
        self.depth = WHD[2]
        self.weight = weight
        # Packing Priority level ,choose 1-3
        self.level = level
        # loadbear
        self.loadbear = loadbear
        # Upside down? True or False
        self.updown = updown if typeof == 'cube' else False
        # Draw item color
        self.color = color
        self.rotation_type = 0
        self.position = START_POSITION
        self.number_of_decimals = DEFAULT_NUMBER_OF_DECIMALS


    def formatNumbers(self, number_of_decimals):
        ''' '''
        self.width = set2Decimal(self.width, number_of_decimals)
        self.height = set2Decimal(self.height, number_of_decimals)
        self.depth = set2Decimal(self.depth, number_of_decimals)
        self.weight = set2Decimal(self.weight, number_of_decimals)
        self.number_of_decimals = number_of_decimals


    def string(self):
        ''' '''
        return "%s(%sx%sx%s, weight: %s) pos(%s) rt(%s) vol(%s)" % (
            self.partno, self.width, self.height, self.depth, self.weight,
            self.position, self.rotation_type, self.getVolume()
        )


    def getVolume(self):
        ''' '''
        return set2Decimal(self.width * self.height * self.depth, self.number_of_decimals)


    def getMaxArea(self):
        ''' '''
        a = sorted([self.width,self.height,self.depth],reverse=True) if self.updown == True else [self.width,self.height,self.depth]
    
        return set2Decimal(a[0] * a[1] , self.number_of_decimals)


    def getDimension(self):
        ''' rotation type '''
        if self.rotation_type == RotationType.RT_WHD:
            dimension = [self.width, self.height, self.depth]
        elif self.rotation_type == RotationType.RT_HWD:
            dimension = [self.height, self.width, self.depth]
        elif self.rotation_type == RotationType.RT_HDW:
            dimension = [self.height, self.depth, self.width]
        elif self.rotation_type == RotationType.RT_DHW:
            dimension = [self.depth, self.height, self.width]
        elif self.rotation_type == RotationType.RT_DWH:
            dimension = [self.depth, self.width, self.height]
        elif self.rotation_type == RotationType.RT_WDH:
            dimension = [self.width, self.depth, self.height]
        else:
            dimension = []

        return dimension



class Bin:

    def __init__(self, partno, WHD, max_weight,corner=0,put_type=1):
        ''' '''
        self.partno = partno
        self.width = WHD[0]
        self.height = WHD[1]
        self.depth = WHD[2]
        self.max_weight = max_weight
        self.corner = corner
        self.items = []
        self.fit_items = np.array([[0,WHD[0],0,WHD[1],0,0]])
        self.unfitted_items = []
        self.number_of_decimals = DEFAULT_NUMBER_OF_DECIMALS
        self.fix_point = False
        self.check_stable = False
        self.support_surface_ratio = 0
        self.put_type = put_type
        # used to put gravity distribution
        self.gravity = []


    def formatNumbers(self, number_of_decimals):
        ''' '''
        self.width = set2Decimal(self.width, number_of_decimals)
        self.height = set2Decimal(self.height, number_of_decimals)
        self.depth = set2Decimal(self.depth, number_of_decimals)
        self.max_weight = set2Decimal(self.max_weight, number_of_decimals)
        self.number_of_decimals = number_of_decimals


    def string(self):
        ''' '''
        return "%s(%sx%sx%s, max_weight:%s) vol(%s)" % (
            self.partno, self.width, self.height, self.depth, self.max_weight,
            self.getVolume()
        )


    def getVolume(self):
        ''' '''
        return set2Decimal(
            self.width * self.height * self.depth, self.number_of_decimals
        )


    def getTotalWeight(self):
        ''' '''
        total_weight = 0

        for item in self.items:
            total_weight += item.weight

        return set2Decimal(total_weight, self.number_of_decimals)


    def putItem(self, item, pivot, axis=None, z_min=None, z_max=None):
        ''' put item in bin.

        Optional strict depth-zone clamps (backward compatible — both
        default to None = no clamping, existing callers unaffected):
          z_min: item's depth-start (pivot z) must be >= z_min. Prevents
                 backfilling a gap left in an earlier (deeper) zone.
          z_max: item's depth-end (pivot z + depth) must be <= z_max.
                 Keeps the item inside its own zone; overflow is handled
                 by the caller cascading the item forward (toward the door).
        '''
        fit = False
        valid_item_position = item.position
        item.position = pivot
        rotate = RotationType.ALL if item.updown == True else RotationType.Notupdown

        # Zone floor guard: reject any pivot that sits behind (deeper than)
        # the zone's back wall. Without this, a face-pivot generated from a
        # box in a deeper zone can land inside the current zone's forbidden
        # space, which would violate LIFO (low-sequence boxes backfilling
        # near high-sequence boxes). 5e-4 = half a 3-decimal quantization
        # step (zone floors are quantized to 3 decimals and can sit up to
        # 0.0005 below a fractional floor, which a tiny epsilon would
        # reject).
        if z_min is not None:
            try:
                if float(pivot[2]) < float(z_min) - 5e-4:
                    item.position = valid_item_position
                    return False
            except (TypeError, IndexError):
                pass

        # Iterate over the rotation types themselves (not their positions in
        # the list). The old `for i in range(len(rotate)): item.rotation_type = i`
        # silently ignored the contents of `rotate` and only ever tried the
        # first N poses — so Notupdown = [RT_WHD, RT_HWD] was the *only* combo
        # that "worked", and it even permitted a tip-over. Using the values
        # makes the allowed-list an actual source of truth.
        for rotation_type in rotate:
            item.rotation_type = rotation_type
            dimension = item.getDimension()
            # rotate
            # NOTE: pivot may carry Decimals (first-item path reuses
            # bin.fit_items entries) while dimension entries may be Decimal
            # or float — compare in float space so mixed types never raise.
            try:
                _px, _py, _pz = float(pivot[0]), float(pivot[1]), float(pivot[2])
                _dw, _dh, _dd = float(dimension[0]), float(dimension[1]), float(dimension[2])
            except (TypeError, IndexError, ValueError):
                continue
            if (
                float(self.width) < _px + _dw or
                float(self.height) < _py + _dh or
                float(self.depth) < _pz + _dd
            ):
                continue
            # Zone ceiling guard: reject any rotation whose depth-end exceeds
            # the zone's front wall. Combined with the floor guard above,
            # this keeps the box fully inside its own zone; the caller
            # cascades overflow forward toward the door instead.
            if z_max is not None:
                try:
                    if _pz + _dd > float(z_max) + 5e-4:
                        continue
                except (TypeError, IndexError):
                    pass

            fit = True

            for current_item_in_bin in self.items:
                if intersect(current_item_in_bin, item):
                    fit = False
                    break

            if fit:
                # cal total weight
                if self.getTotalWeight() + item.weight > self.max_weight:
                    fit = False
                    return fit

                # STRICT ZONE fast path: when the caller supplies depth-zone
                # clamps, skip the origin-anchored fix-point + stability logic
                # (which would slide boxes back toward the back wall and break
                # LIFO). Place the box exactly at the already-validated pivot,
                # re-check collision there, and register it. This keeps every
                # box inside its own zone so same-sequence boxes stay
                # contiguous and low-sequence boxes can never backfill near
                # high-sequence boxes.
                if z_min is not None or z_max is not None:
                    item.position = [set2Decimal(_px, 3), set2Decimal(_py, 3), set2Decimal(_pz, 3)]
                    _collides = False
                    for current_item_in_bin in self.items:
                        try:
                            if intersect(current_item_in_bin, item):
                                _collides = True
                                break
                        except TypeError:
                            # Mixed Decimal/float positions — normalize and retry once.
                            try:
                                item.position = [set2Decimal(float(v)) for v in item.position]
                                if intersect(current_item_in_bin, item):
                                    _collides = True
                                    break
                            except (TypeError, ValueError, IndexError):
                                _collides = True
                                break
                    if _collides:
                        item.position = valid_item_position
                        return False
                    self.fit_items = np.append(
                        self.fit_items,
                        np.array([[_px, _px + _dw, _py, _py + _dh, _pz, _pz + _dd]]),
                        axis=0,
                    )
                    item.position = [set2Decimal(_px, 3), set2Decimal(_py, 3), set2Decimal(_pz, 3)]
                    self.items.append(copy.deepcopy(item))
                    return True

                # fix point float prob
                if self.fix_point == True :
                        
                    [w,h,d] = dimension
                    [x,y,z] = [float(pivot[0]),float(pivot[1]),float(pivot[2])]

                    for _ in range(3):
                        y_prev, x_prev, z_prev = y, x, z
                        # fix height
                        y = self.checkHeight([x,x+float(w),y,y+float(h),z,z+float(d)])
                        # fix width
                        x = self.checkWidth([x,x+float(w),y,y+float(h),z,z+float(d)])
                        # fix depth
                        z = self.checkDepth([x,x+float(w),y,y+float(h),z,z+float(d)])
                        # Converged: deterministic in (x,y,z) -> stop.
                        if (x, y, z) == (x_prev, y_prev, z_prev):
                            break

                    # BUG FIX: checkHeight/checkWidth/checkDepth above can move
                    # the item to a different (x, y, z) than the pivot position
                    # that was already collision-checked against self.items
                    # (lines ~165-168). Nothing re-validates the ADJUSTED spot
                    # against existing items - only a support/stability check
                    # runs below, which can pass even when boxes now overlap.
                    # Re-run the same intersect() check at the fixed position
                    # before committing to it, and fail the placement (instead
                    # of silently overlapping) if it collides.
                    item.position = [set2Decimal(x), set2Decimal(y), set2Decimal(z)]
                    for current_item_in_bin in self.items:
                        if intersect(current_item_in_bin, item):
                            item.position = valid_item_position
                            fit = False
                            return fit

                    # check stability on item
                    # rule :
                    # 1. Define a support ratio, if the ratio below the support surface does not exceed this ratio, compare the second rule.
                    # 2. If there is no support under any vertices of the bottom of the item, then fit = False.
                    # 3. Center of mass must be supported (the item's footprint center must rest on a supporter or the bin floor).
                    #
                    # "Below" is the vertical (height) axis, i.e. pivot's y / self.height,
                    # NOT the depth (z) axis. The supporting surface is therefore the
                    # item's *footprint* -- its width x depth (x/z) plane -- measured
                    # against other items whose top face (i[3], their y1) sits exactly
                    # at this item's bottom (y). An item resting directly on the bin
                    # floor (y == 0) is always fully supported.
                    MIN_VERTEX_RULE_SUPPORT = 0.25  # minimum support ratio to allow the 4-vertex fallback
                    if self.check_stable == True :
                        if y == 0 :
                            support_area_upper = None  # fully supported by the bin floor
                            center_supported = True
                        else :
                            # Cal the footprint (width x depth) area of the item.
                            item_area_lower = int(dimension[0] * dimension[2])
                            # Cal the area of the underlying support.
                            support_area_upper = 0
                            center_supported = False
                            for i in self.fit_items:
                                # Verify that the lower support surface area is greater than the upper support surface area * support_surface_ratio.
                                if y == i[3] :
                                    ix0 = int(x); ix1 = int(x + int(w))
                                    jx0 = int(i[0]); jx1 = int(i[1])
                                    iz0 = int(z); iz1 = int(z + int(d))
                                    jz0 = int(i[4]); jz1 = int(i[5])
                                    ox = (min(ix1, jx1) - max(ix0, jx0)) if (max(ix0, jx0) < min(ix1, jx1)) else 0
                                    oz = (min(iz1, jz1) - max(iz0, jz0)) if (max(iz0, jz0) < min(iz1, jz1)) else 0
                                    area = ox * oz
                                    support_area_upper += area
                                    # Track whether the item's center of mass is supported
                                    cx = x + float(w) / 2
                                    cz = z + float(d) / 2
                                    if (i[0] <= cx <= i[1]) and (i[4] <= cz <= i[5]):
                                        center_supported = True

                        # Check stability rules
                        stable = True
                        if support_area_upper is not None:
                            # Rule 1: support ratio must meet threshold
                            if support_area_upper / item_area_lower < self.support_surface_ratio:
                                # Rule 2: four vertices (only if minimum support met)
                                if support_area_upper / item_area_lower < MIN_VERTEX_RULE_SUPPORT:
                                    stable = False
                                else:
                                    four_vertices = [[x,z],[x+float(w),z],[x,z+float(d)],[x+float(w),z+float(d)]]
                                    c = [False,False,False,False]
                                    for i in self.fit_items:
                                        if y == i[3] :
                                            for jdx,j in enumerate(four_vertices) :
                                                if (i[0] <= j[0] <= i[1]) and (i[4] <= j[1] <= i[5]) :
                                                    c[jdx] = True
                                    if False in c:
                                        stable = False
                            # Rule 3: center of mass must be supported
                            if stable and not center_supported:
                                stable = False

                        if not stable:
                            # Slide-to-support rescue: try sliding toward the largest supporter
                            rescued = False
                            if support_area_upper is not None and support_area_upper > 0:
                                # Find the largest supporter
                                best_supporter = None
                                best_area = 0
                                for i in self.fit_items:
                                    if y == i[3]:
                                        ix0 = int(x); ix1 = int(x + int(w))
                                        jx0 = int(i[0]); jx1 = int(i[1])
                                        iz0 = int(z); iz1 = int(z + int(d))
                                        jz0 = int(i[4]); jz1 = int(i[5])
                                        ox = (min(ix1, jx1) - max(ix0, jx0)) if (max(ix0, jx0) < min(ix1, jx1)) else 0
                                        oz = (min(iz1, jz1) - max(iz0, jz0)) if (max(iz0, jz0) < min(iz1, jz1)) else 0
                                        area = ox * oz
                                        if area > best_area:
                                            best_area = area
                                            best_supporter = i
                                if best_supporter is not None:
                                    sup_cx = (best_supporter[0] + best_supporter[1]) / 2
                                    sup_cz = (best_supporter[4] + best_supporter[5]) / 2
                                    item_cx = x + float(w) / 2
                                    item_cz = z + float(d) / 2
                                    slide_x = sup_cx - item_cx
                                    slide_z = sup_cz - item_cz
                                    slide_dist = (slide_x ** 2 + slide_z ** 2) ** 0.5
                                    if slide_dist > 0.5:
                                        for factor in [1.0, 0.5, 1.5]:
                                            trial_x = x + slide_x * factor
                                            trial_z = z + slide_z * factor
                                            trial_x = max(0.0, min(trial_x, float(self.width) - float(w)))
                                            trial_z = max(0.0, min(trial_z, float(self.depth) - float(d)))
                                            item.position = [set2Decimal(trial_x), set2Decimal(y), set2Decimal(trial_z)]
                                            collision = False
                                            for current_item_in_bin in self.items:
                                                if intersect(current_item_in_bin, item):
                                                    collision = True
                                                    break
                                            if collision:
                                                continue
                                            trial_stable = True
                                            trial_support = 0
                                            trial_center_ok = False
                                            for i in self.fit_items:
                                                if y == i[3]:
                                                    ix0 = int(trial_x); ix1 = int(trial_x + int(w))
                                                    jx0 = int(i[0]); jx1 = int(i[1])
                                                    iz0 = int(trial_z); iz1 = int(trial_z + int(d))
                                                    jz0 = int(i[4]); jz1 = int(i[5])
                                                    ox = (min(ix1, jx1) - max(ix0, jx0)) if (max(ix0, jx0) < min(ix1, jx1)) else 0
                                                    oz = (min(iz1, jz1) - max(iz0, jz0)) if (max(iz0, jz0) < min(iz1, jz1)) else 0
                                                    trial_support += ox * oz
                                                    cx = trial_x + float(w) / 2
                                                    cz = trial_z + float(d) / 2
                                                    if (i[0] <= cx <= i[1]) and (i[4] <= cz <= i[5]):
                                                        trial_center_ok = True
                                            if trial_support / item_area_lower < self.support_surface_ratio:
                                                if trial_support / item_area_lower < MIN_VERTEX_RULE_SUPPORT:
                                                    trial_stable = False
                                                else:
                                                    four_vertices = [[trial_x,trial_z],[trial_x+float(w),trial_z],[trial_x,trial_z+float(d)],[trial_x+float(w),trial_z+float(d)]]
                                                    c = [False,False,False,False]
                                                    for i in self.fit_items:
                                                        if y == i[3]:
                                                            for jdx,j in enumerate(four_vertices):
                                                                if (i[0] <= j[0] <= i[1]) and (i[4] <= j[1] <= i[5]):
                                                                    c[jdx] = True
                                                    if False in c:
                                                        trial_stable = False
                                            if trial_stable and not trial_center_ok:
                                                trial_stable = False
                                            if trial_stable:
                                                x = trial_x
                                                z = trial_z
                                                rescued = True
                                                break
                            if not rescued:
                                item.position = valid_item_position
                                fit = False
                                return fit

                    self.fit_items = np.append(self.fit_items,np.array([[x,x+float(w),y,y+float(h),z,z+float(d)]]),axis=0)
                    item.position = [set2Decimal(x),set2Decimal(y),set2Decimal(z)]

                if fit :
                    self.items.append(copy.deepcopy(item))

            else :
                item.position = valid_item_position

            return fit

        else :
            item.position = valid_item_position

        return fit


    def checkDepth(self,unfix_point):
        ''' fix item position z '''
        z_ = [[0,0],[float(self.depth),float(self.depth)]]
        for j in self.fit_items:
            x0 = int(j[0]); x1 = int(j[1])
            x2 = int(unfix_point[0]); x3 = int(unfix_point[1])
            if x0 < x3 and x2 < x1:
                y0 = int(j[2]); y1 = int(j[3])
                y2 = int(unfix_point[2]); y3 = int(unfix_point[3])
                if y0 < y3 and y2 < y1:
                    z_.append([float(j[4]), float(j[5])])
        top_depth = unfix_point[5] - unfix_point[4]
        # find diff set on z_.
        z_ = sorted(z_, key = lambda z_ : z_[1])
        for j in range(len(z_)-1):
            if z_[j+1][0] -z_[j][1] >= top_depth:
                return z_[j][1]
        return unfix_point[4]


    def checkWidth(self,unfix_point):
        ''' fix item position x ''' 
        x_ = [[0,0],[float(self.width),float(self.width)]]
        for j in self.fit_items:
            z0 = int(j[4]); z1 = int(j[5])
            z2 = int(unfix_point[4]); z3 = int(unfix_point[5])
            if z0 < z3 and z2 < z1:
                y0 = int(j[2]); y1 = int(j[3])
                y2 = int(unfix_point[2]); y3 = int(unfix_point[3])
                if y0 < y3 and y2 < y1:
                    x_.append([float(j[0]), float(j[1])])
        top_width = unfix_point[1] - unfix_point[0]
        # find diff set on x_bottom and x_top.
        x_ = sorted(x_,key = lambda x_ : x_[1])
        for j in range(len(x_)-1):
            if x_[j+1][0] -x_[j][1] >= top_width:
                return x_[j][1]
        return unfix_point[0]
    

    def checkHeight(self,unfix_point):
        '''fix item position y '''
        y_ = [[0,0],[float(self.height),float(self.height)]]
        for j in self.fit_items:
            x0 = int(j[0]); x1 = int(j[1])
            x2 = int(unfix_point[0]); x3 = int(unfix_point[1])
            if x0 < x3 and x2 < x1:
                z0 = int(j[4]); z1 = int(j[5])
                z2 = int(unfix_point[4]); z3 = int(unfix_point[5])
                if z0 < z3 and z2 < z1:
                    y_.append([float(j[2]), float(j[3])])
        top_height = unfix_point[3] - unfix_point[2]
        # find diff set on y_bottom and y_top.
        y_ = sorted(y_,key = lambda y_ : y_[1])
        for j in range(len(y_)-1):
            if y_[j+1][0] -y_[j][1] >= top_height:
                return y_[j][1]

        return unfix_point[2]


    def addCorner(self):
        '''add container coner '''
        if self.corner != 0 :
            corner = set2Decimal(self.corner)
            corner_list = []
            for i in range(8):
                a = Item(
                    partno='corner{}'.format(i),
                    name='corner', 
                    typeof='cube',
                    WHD=(corner,corner,corner), 
                    weight=0, 
                    level=0, 
                    loadbear=0, 
                    updown=True, 
                    color='#000000')

                corner_list.append(a)
            return corner_list


    def putCorner(self,info,item):
        '''put coner in bin '''
        fit = False
        x = set2Decimal(self.width - self.corner)
        y = set2Decimal(self.height - self.corner)
        z = set2Decimal(self.depth - self.corner)
        pos = [[0,0,0],[0,0,z],[0,y,z],[0,y,0],[x,y,0],[x,0,0],[x,0,z],[x,y,z]]
        item.position = pos[info]
        self.items.append(item)

        corner = [float(item.position[0]),float(item.position[0])+float(self.corner),float(item.position[1]),float(item.position[1])+float(self.corner),float(item.position[2]),float(item.position[2])+float(self.corner)]

        self.fit_items = np.append(self.fit_items,np.array([corner]),axis=0)
        return


    def clearBin(self):
        ''' clear item which in bin '''
        self.items = []
        self.fit_items = np.array([[0,self.width,0,self.height,0,0]])
        return


class Packer:

    def __init__(self):
        ''' '''
        self.bins = []
        self.items = []
        self.unfit_items = []
        self.total_items = 0
        self.binding = []
        # self.apex = []


    def addBin(self, bin):
        ''' '''
        return self.bins.append(bin)


    def addItem(self, item):
        ''' '''
        self.total_items = len(self.items) + 1

        return self.items.append(item)


    def pack2Bin(self, bin, item, fix_point, check_stable, support_surface_ratio, z_min=None, z_max=None):
        ''' pack item to bin.

        Optional strict depth-zone clamps (backward compatible — both
        default to None = no clamping, existing callers unaffected):
          z_min / z_max: forwarded to Bin.putItem; see its docstring.
        '''
        fitted = False
        bin.fix_point = fix_point
        bin.check_stable = check_stable
        bin.support_surface_ratio = support_surface_ratio

        # first put item on (0,0,0) , if corner exist ,first add corner in box.
        if bin.corner != 0 and not bin.items:
            corner_lst = bin.addCorner()
            for i in range(len(corner_lst)) :
                bin.putCorner(i,corner_lst[i])

        elif not bin.items:
            response = bin.putItem(item, item.position, z_min=z_min, z_max=z_max)

            if not response:
                bin.unfitted_items.append(item)
            return

        for axis in range(0, 3):
            items_in_bin = bin.items
            for ib in items_in_bin:
                pivot = [0, 0, 0]
                w, h, d = ib.getDimension()
                if axis == Axis.WIDTH:
                    pivot = [ib.position[0] + w,ib.position[1],ib.position[2]]
                elif axis == Axis.HEIGHT:
                    pivot = [ib.position[0],ib.position[1] + h,ib.position[2]]
                elif axis == Axis.DEPTH:
                    pivot = [ib.position[0],ib.position[1],ib.position[2] + d]

                if bin.putItem(item, pivot, axis, z_min=z_min, z_max=z_max):
                    fitted = True
                    break
            if fitted:
                break

        # STRICT ZONE floor-starter: if no face-pivot worked (common for the
        # first box of a new zone, whose floor sits ahead of every existing
        # pivot), seed the zone with a single attempt at (0, 0, floor). This
        # is O(placed) — a single putItem call, no loop, no scan — so zero
        # perf risk. The z_min guard inside putItem accepts this pivot
        # (== floor), while every other pivot stayed behind the floor.
        if not fitted and z_min is not None:
            try:
                _starter = [set2Decimal(0, 3), set2Decimal(0, 3), set2Decimal(z_min, 3)]
            except (TypeError, ValueError):
                _starter = None
            if _starter is not None and bin.putItem(
                item, _starter, Axis.DEPTH, z_min=z_min, z_max=z_max
            ):
                fitted = True

        if not fitted:
            bin.unfitted_items.append(item)


    def sortBinding(self,bin):
        ''' sorted by binding '''
        b,front,back = [],[],[]
        for i in range(len(self.binding)):
            b.append([]) 
            for item in self.items:
                if item.name in self.binding[i]:
                    b[i].append(item)
                elif item.name not in self.binding:
                    if len(b[0]) == 0 and item not in front:
                        front.append(item)
                    elif item not in back and item not in front:
                        back.append(item)

        min_c = min([len(i) for i in b])
        
        sort_bind =[]
        for i in range(min_c):
            for j in range(len(b)):
                sort_bind.append(b[j][i])
        
        for i in b:
            for j in i:
                if j not in sort_bind:
                    self.unfit_items.append(j)

        self.items = front + sort_bind + back
        return


    def putOrder(self):
        '''Arrange the order of items '''
        r = []
        for i in self.bins:
            # open top container
            if i.put_type == 2:
                i.items.sort(key=lambda item: item.position[0], reverse=False)
                i.items.sort(key=lambda item: item.position[1], reverse=False)
                i.items.sort(key=lambda item: item.position[2], reverse=False)
            # general container
            elif i.put_type == 1:
                i.items.sort(key=lambda item: item.position[1], reverse=False)
                i.items.sort(key=lambda item: item.position[2], reverse=False)
                i.items.sort(key=lambda item: item.position[0], reverse=False)
            else :
                pass
        return


    def gravityCenter(self,bin):
        ''' 
        Deviation Of Cargo gravity distribution
        ''' 
        w = int(bin.width)
        h = int(bin.height)
        d = int(bin.depth)

        area1 = [set(range(0,w//2+1)),set(range(0,h//2+1)),0]
        area2 = [set(range(w//2+1,w+1)),set(range(0,h//2+1)),0]
        area3 = [set(range(0,w//2+1)),set(range(h//2+1,h+1)),0]
        area4 = [set(range(w//2+1,w+1)),set(range(h//2+1,h+1)),0]
        area = [area1,area2,area3,area4]

        for i in bin.items:

            x_st = int(i.position[0])
            y_st = int(i.position[1])
            if i.rotation_type == 0:
                x_ed = int(i.position[0] + i.width)
                y_ed = int(i.position[1] + i.height)
            elif i.rotation_type == 1:
                x_ed = int(i.position[0] + i.height)
                y_ed = int(i.position[1] + i.width)
            elif i.rotation_type == 2:
                x_ed = int(i.position[0] + i.height)
                y_ed = int(i.position[1] + i.depth)
            elif i.rotation_type == 3:
                x_ed = int(i.position[0] + i.depth)
                y_ed = int(i.position[1] + i.height)
            elif i.rotation_type == 4:
                x_ed = int(i.position[0] + i.depth)
                y_ed = int(i.position[1] + i.width)
            elif i.rotation_type == 5:
                x_ed = int(i.position[0] + i.width)
                y_ed = int(i.position[1] + i.depth)

            x_set = set(range(x_st,int(x_ed)+1))
            y_set = set(range(y_st,y_ed+1))

            # cal gravity distribution
            for j in range(len(area)):
                if x_set.issubset(area[j][0]) and y_set.issubset(area[j][1]) : 
                    area[j][2] += int(i.weight)
                    break
                # include x and !include y
                elif x_set.issubset(area[j][0]) == True and y_set.issubset(area[j][1]) == False and len(y_set & area[j][1]) != 0 : 
                    y = len(y_set & area[j][1]) / (y_ed - y_st) * int(i.weight)
                    area[j][2] += y
                    if j >= 2 :
                        area[j-2][2] += (int(i.weight) - x)
                    else :
                        area[j+2][2] += (int(i.weight) - y)
                    break
                # include y and !include x
                elif x_set.issubset(area[j][0]) == False and y_set.issubset(area[j][1]) == True and len(x_set & area[j][0]) != 0 : 
                    x = len(x_set & area[j][0]) / (x_ed - x_st) * int(i.weight)
                    area[j][2] += x
                    if j >= 2 :
                        area[j-2][2] += (int(i.weight) - x)
                    else :
                        area[j+2][2] += (int(i.weight) - x)
                    break
                # !include x and !include y
                elif x_set.issubset(area[j][0])== False and y_set.issubset(area[j][1]) == False and len(y_set & area[j][1]) != 0  and len(x_set & area[j][0]) != 0 :
                    all = (y_ed - y_st) * (x_ed - x_st)
                    y = len(y_set & area[0][1])
                    y_2 = y_ed - y_st - y
                    x = len(x_set & area[0][0])
                    x_2 = x_ed - x_st - x
                    area[0][2] += x * y / all * int(i.weight)
                    area[1][2] += x_2 * y / all * int(i.weight)
                    area[2][2] += x * y_2 / all * int(i.weight)
                    area[3][2] += x_2 * y_2 / all * int(i.weight)
                    break
            
        r = [area[0][2],area[1][2],area[2][2],area[3][2]]
        result = []
        for i in r :
            result.append(round(i / sum(r) * 100,2))
        return result


    def pack(self, bigger_first=False,distribute_items=True,fix_point=True,check_stable=True,support_surface_ratio=0.75,binding=[],number_of_decimals=DEFAULT_NUMBER_OF_DECIMALS):
        '''pack master func '''
        # set decimals
        for bin in self.bins:
            bin.formatNumbers(number_of_decimals)

        for item in self.items:
            item.formatNumbers(number_of_decimals)
        # add binding attribute
        self.binding = binding
        # Bin : sorted by volumn
        self.bins.sort(key=lambda bin: bin.getVolume(), reverse=bigger_first)
        # Item : sorted by volumn -> sorted by loadbear -> sorted by level -> binding
        self.items.sort(key=lambda item: item.getVolume(), reverse=bigger_first)
        # self.items.sort(key=lambda item: item.getMaxArea(), reverse=bigger_first)
        self.items.sort(key=lambda item: item.loadbear, reverse=True)
        self.items.sort(key=lambda item: item.level, reverse=False)
        # sorted by binding
        if binding != []:
            self.sortBinding(bin)

        for idx,bin in enumerate(self.bins):
            # pack item to bin
            for item in self.items:
                self.pack2Bin(bin, item, fix_point, check_stable, support_surface_ratio)

            if binding != []:
                # resorted
                self.items.sort(key=lambda item: item.getVolume(), reverse=bigger_first)
                self.items.sort(key=lambda item: item.loadbear, reverse=True)
                self.items.sort(key=lambda item: item.level, reverse=False)
                # clear bin
                bin.items = []
                bin.unfitted_items = self.unfit_items
                bin.fit_items = np.array([[0,bin.width,0,bin.height,0,0]])
                # repacking
                for item in self.items:
                    self.pack2Bin(bin, item,fix_point,check_stable,support_surface_ratio)
            
            # Deviation Of Cargo Gravity Center 
            self.bins[idx].gravity = self.gravityCenter(bin)

            if distribute_items :
                for bitem in bin.items:
                    no = bitem.partno
                    for item in self.items :
                        if item.partno == no :
                            self.items.remove(item)
                            break

        # --- Orientation enforcement audit (defence-in-depth) ----------------
        # Steps 1 + 2 already guarantee putItem only ever assigns an allowed
        # rotation, but this guard makes the rule explicit at the output
        # boundary: any item flagged updown=False that somehow ended up in a
        # tipped pose is moved to unfitted_items instead of being silently
        # shipped as a forbidden "(_I_) flip".
        for bin in self.bins:
            still_fitted = []
            for item in bin.items:
                if item.updown == False and item.rotation_type not in RotationType.Notupdown:
                    bin.unfitted_items.append(item)
                else:
                    still_fitted.append(item)
            bin.items = still_fitted

        # put order of items
        self.putOrder()

        if self.items != []:
            self.unfit_items = copy.deepcopy(self.items)
            self.items = []
        # for item in self.items.copy():
        #     if item in bin.unfitted_items:
        #         self.items.remove(item)



class Painter:

    def __init__(self,bins):
        ''' '''
        self.items = bins.items
        self.width = bins.width
        self.height = bins.height
        self.depth = bins.depth


    def _plotCube(self, ax, x, y, z, dx, dy, dz, color='red',mode=2,linewidth=1,text="",fontsize=15,alpha=0.5):
        """ Auxiliary function to plot a cube. code taken somewhere from the web.  """
        xx = [x, x, x+dx, x+dx, x]
        yy = [y, y+dy, y+dy, y, y]
        
        kwargs = {'alpha': 1, 'color': color,'linewidth':linewidth }
        if mode == 1 :
            ax.plot3D(xx, yy, [z]*5, **kwargs)
            ax.plot3D(xx, yy, [z+dz]*5, **kwargs)
            ax.plot3D([x, x], [y, y], [z, z+dz], **kwargs)
            ax.plot3D([x, x], [y+dy, y+dy], [z, z+dz], **kwargs)
            ax.plot3D([x+dx, x+dx], [y+dy, y+dy], [z, z+dz], **kwargs)
            ax.plot3D([x+dx, x+dx], [y, y], [z, z+dz], **kwargs)
        else :
            p = Rectangle((x,y),dx,dy,fc=color,ec='black',alpha = alpha)
            p2 = Rectangle((x,y),dx,dy,fc=color,ec='black',alpha = alpha)
            p3 = Rectangle((y,z),dy,dz,fc=color,ec='black',alpha = alpha)
            p4 = Rectangle((y,z),dy,dz,fc=color,ec='black',alpha = alpha)
            p5 = Rectangle((x,z),dx,dz,fc=color,ec='black',alpha = alpha)
            p6 = Rectangle((x,z),dx,dz,fc=color,ec='black',alpha = alpha)
            ax.add_patch(p)
            ax.add_patch(p2)
            ax.add_patch(p3)
            ax.add_patch(p4)
            ax.add_patch(p5)
            ax.add_patch(p6)
            
            if text != "":
                ax.text( (x+ dx/2), (y+ dy/2), (z+ dz/2), str(text),color='black', fontsize=fontsize, ha='center', va='center')

            art3d.pathpatch_2d_to_3d(p, z=z, zdir="z")
            art3d.pathpatch_2d_to_3d(p2, z=z+dz, zdir="z")
            art3d.pathpatch_2d_to_3d(p3, z=x, zdir="x")
            art3d.pathpatch_2d_to_3d(p4, z=x + dx, zdir="x")
            art3d.pathpatch_2d_to_3d(p5, z=y, zdir="y")
            art3d.pathpatch_2d_to_3d(p6, z=y + dy, zdir="y")


    def _plotCylinder(self, ax, x, y, z, dx, dy, dz, color='red',mode=2,text="",fontsize=10,alpha=0.2):
        """ Auxiliary function to plot a Cylinder  """
        # plot the two circles above and below the cylinder
        p = Circle((x+dx/2,y+dy/2),radius=dx/2,color=color,alpha=0.5)
        p2 = Circle((x+dx/2,y+dy/2),radius=dx/2,color=color,alpha=0.5)
        ax.add_patch(p)
        ax.add_patch(p2)
        art3d.pathpatch_2d_to_3d(p, z=z, zdir="z")
        art3d.pathpatch_2d_to_3d(p2, z=z+dz, zdir="z")
        # plot a circle in the middle of the cylinder
        center_z = np.linspace(0, dz, 10)
        theta = np.linspace(0, 2*np.pi, 10)
        theta_grid, z_grid=np.meshgrid(theta, center_z)
        x_grid = dx / 2 * np.cos(theta_grid) + x + dx / 2
        y_grid = dy / 2 * np.sin(theta_grid) + y + dy / 2
        z_grid = z_grid + z
        ax.plot_surface(x_grid, y_grid, z_grid,shade=False,fc=color,alpha=alpha,color=color)
        if text != "" :
            ax.text( (x+ dx/2), (y+ dy/2), (z+ dz/2), str(text),color='black', fontsize=fontsize, ha='center', va='center')

    def plotBoxAndItems(self,title="",alpha=0.2,write_num=False,fontsize=10):
        """ side effective. Plot the Bin and the items it contains. """
        fig = plt.figure()
        axGlob = plt.axes(projection='3d')
        
        # plot bin 
        self._plotCube(axGlob,0, 0, 0, float(self.width), float(self.height), float(self.depth),color='black',mode=1,linewidth=2,text="")

        counter = 0
        # fit rotation type
        for item in self.items:
            rt = item.rotation_type  
            x,y,z = item.position
            [w,h,d] = item.getDimension()
            color = item.color
            text= item.partno if write_num else ""

            if item.typeof == 'cube':
                 # plot item of cube
                self._plotCube(axGlob, float(x), float(y), float(z), float(w),float(h),float(d),color=color,mode=2,text=text,fontsize=fontsize,alpha=alpha)
            elif item.typeof == 'cylinder':
                # plot item of cylinder
                self._plotCylinder(axGlob, float(x), float(y), float(z), float(w),float(h),float(d),color=color,mode=2,text=text,fontsize=fontsize,alpha=alpha)
            
            counter = counter + 1  

        
        plt.title(title)
        self.setAxesEqual(axGlob)
        return plt


    def setAxesEqual(self,ax):
        '''Make axes of 3D plot have equal scale so that spheres appear as spheres,
        cubes as cubes, etc..  This is one possible solution to Matplotlib's
        ax.set_aspect('equal') and ax.axis('equal') not working for 3D.

        Input
        ax: a matplotlib axis, e.g., as output from plt.gca().'''
        x_limits = ax.get_xlim3d()
        y_limits = ax.get_ylim3d()
        z_limits = ax.get_zlim3d()

        x_range = abs(x_limits[1] - x_limits[0])
        x_middle = np.mean(x_limits)
        y_range = abs(y_limits[1] - y_limits[0])
        y_middle = np.mean(y_limits)
        z_range = abs(z_limits[1] - z_limits[0])
        z_middle = np.mean(z_limits)

        # The plot bounding box is a sphere in the sense of the infinity
        # norm, hence I call half the max range the plot radius.
        plot_radius = 0.5 * max([x_range, y_range, z_range])

        ax.set_xlim3d([x_middle - plot_radius, x_middle + plot_radius])
        ax.set_ylim3d([y_middle - plot_radius, y_middle + plot_radius])
        ax.set_zlim3d([z_middle - plot_radius, z_middle + plot_radius])