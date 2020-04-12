import cv2
import numpy as np
import shapefile
import os


# Produces tehnokeskuse defect mask (library version)
def filimage(path, shpath, fname):

    # The shape file is assumed to be one directory up than the orthophotos
    path = path.strip("\\")  # Remove trailing slash
    path += os.path.sep  # Reintroduce trailing slash

    # read the image file and the mask
    img = cv2.imread(path + fname + '.jpg')
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    mask = cv2.imread(path + fname + '.mask.png', 0)
    img2 = img.copy()

    h, w, d = img.shape

    # read the vrt parameters
    koord = runvrt(path + fname + '.vrt')
    # koord[0]...koord[5] to access individual coordinates

    xmin = koord[0]
    xmax = koord[0] + koord[1] * (w - 1)
    ymin = koord[3] + koord[5] * (h - 1)
    ymax = koord[3]

    pnts, tyyp = getdefects(shpath, xmin, xmax, ymin, ymax, koord)

    # different defects are drawn in different colors, can be replaced with a single color
    colors = [(128, 0, 255), (128, 0, 255), (128, 0, 255), (128, 0, 255),
              (128, 0, 255), (128, 0, 255), (128, 0, 255), (128, 0, 255),
              (128, 0, 255)]

    for i in range(0, len(tyyp)):

        pp = np.asarray(pnts[i], dtype=np.int32)

        if tyyp[i] < 5:  # joondefektid
            cv2.polylines(img2, [pp], False, colors[tyyp[i]], 40)
        if 4 < tyyp[i] < 8:  # pinddefektid
            cv2.fillPoly(img2, [pp], colors[tyyp[i]])
        if tyyp[i] == 8:
            cv2.circle(img2, pnts[i][0], 50, colors[tyyp[i]], 25)

    alpha = 0.7
    beta = (1.0 - alpha)
    img2[mask == 0] = (0, 0, 0)
    img2 = cv2.addWeighted(img, alpha, img2, beta, 0.0)

    return img2


def getdefects(path, xmin, xmax, ymin, ymax, koord):
    deflist = ['defects_polygon', 'defects_line', 'defects_point']
    kujutyybid = ['KPIKIPR', 'KVUUK', 'PAIK_J', 'POIKPR', 'SERV', 'VORK', 'PAIK', 'MUREN', 'AUK']

    cnt = np.zeros((9,), dtype=int)
    points = []
    rike = []
    k = 0

    for j in range(3):
        kuju = shapefile.Reader(path + deflist[j])  # three separate defect files

        for i in range(len(kuju.shapes())):
            shape_ex = kuju.shape(i)
            if j == 2:  # point
                x1 = x2 = shape_ex.points[0][0]
                y1 = y2 = shape_ex.points[0][1]
            else:  # not point type defect
                x1 = shape_ex.bbox[0]
                x2 = shape_ex.bbox[2]
                y1 = shape_ex.bbox[1]
                y2 = shape_ex.bbox[3]

                # combinations, I guess

            # if x1>xmin and x2<xmax and y1>ymin and y2<ymax:
            # all defect points are within the image
            # any defect point is within the image
            if xmin < x1 < xmax and ymin < y1 < ymax or xmin < x1 < xmax and ymin < y2 < ymax or xmin < x2 < xmax and ymin < y1 < ymax or xmin < x2 < xmax and ymin < y2 < ymax:

                points.append([])  # = np.zeros((len(shape_ex.points),1))  # a vector of zeroes
                rike.append([])

                for ip in range(len(shape_ex.points)):
                    x = int(round((shape_ex.points[ip][0] - koord[0]) / koord[1]))
                    y = int(round((shape_ex.points[ip][1] - koord[3]) / koord[5]))

                    points[k].append((x, y))
                # now the defect points are in points

                rec = kuju.shapeRecord(i)
                indices = [l for l, s in enumerate(kujutyybid) if
                           rec.record[2] == s]  # the index of the defect type, isnt indices a scalar?
                cnt[indices[0]] += 1  # cnt is a summary over the image
                rike[k] = indices[0]
                k += 1

    return points, rike


def runvrt(fname):
    vrtfile = open(fname, 'r')
    for line in vrtfile:
        if line.find('<GeoTransform>') > -1:
            koord = line[line.find('<GeoTransform>') + 16:line.find('</GeoTransform>')]
            break
    vrtfile.close()
    koord = ''.join(koord)
    koord = np.fromstring(koord, dtype=np.float, sep=',')
    return koord
