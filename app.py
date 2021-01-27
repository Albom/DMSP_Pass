from filelist import FileList
import sys
from os import path
from math import modf
from time import sleep
from datetime import datetime, timedelta, timezone
import requests
import gzip
from random import randint
from PyQt5 import uic
from PyQt5.QtGui import QFont
from PyQt5.QtCore import QThread, pyqtSignal, pyqtSlot, Qt
from PyQt5.QtWidgets import QApplication, \
    QMainWindow, QFileDialog, QMessageBox
from cdflib import CDF, cdfepoch
import warnings
with warnings.catch_warnings():
    warnings.filterwarnings('ignore', category=FutureWarning)
    import h5py


class Formats:

    HEADER_FORMAT = (
        '{:<6s}'          # n
        '{:>4s}'          # sat_id
        '{:>8s}{:>8s}'    # lat, long
        '{:>8s}'          # alt
        '{:>8s}{:>8s}'    # ti, te
        '{:>14s}'         # ne
        '{:>12s}'         # PO+
        '{:>12s}{:>12s}'  # PH+, PHe+
        '{:>6s}{:>6s}'    # RPA, IDM
        '{:>20s}'         # date for satellite
        '{:>10s}'         # ut for satellite
        '{:>10s}'         # mlt
        '{:>10s}'         # mlt from IRI
        '{:>10s}'         # UT for Point
        '{:>20s}'         # date for Point
        '{:>8s}'          # L-Shell
    )

    ROW_FORMAT = (
        '#{:<5d}'           # n
        '{:>4s}'            # sat_id
        '{:8.2f}{:8.2f}'    # lat, long
        '{:>8.2f}'          # alt
        '{:8.1f}{:8.1f}'    # ti, te
        '{:14.5e}'          # ne
        '{:12.3e}'          # PO+
        '{:12.3e}{:12.3e}'  # PH+, PHe+
        '{:6d}{:6d}'        # RPA, IDM
        '{:>20s}'           # date for satellite
        '{:>10.2f}'         # UT for satellite
        '{:>10.2f}'         # mlt
        '{:>10.2f}'         # mlt from IRI
        '{:>10.3f}'         # UT for Point
        '{:>20s}'           # date for Point
        '{:>8.3f}'          # L-Shell
    )

    HEADER = HEADER_FORMAT.format(
        'i',
        'id',
        'lat', 'lon',
        'alt',
        'ti', 'te',
        'ne',
        'po+',
        'ph+', 'phe+',
        'rpa', 'idm',
        'date_sat',
        'ut_sat',
        'mlt_sat',
        'mlt_iri',
        'ut_point',
        'date_point',
        'l_shell'
    )


class MainWnd(QMainWindow):

    def __init__(self):
        super().__init__()
        uic.loadUi('./ui/MainWnd.ui', self)

        self.program_name = 'Sat_Pass version 1.7'
        self.setWindowTitle(self.program_name)

        self.showMaximized()

        self.runButton.clicked.connect(self.run)
        self.aboutButton.clicked.connect(self.show_about)
        self.terminateButton.clicked.connect(self.terminate)
        self.chooseInputFileButton.clicked.connect(self.choose_file)
        self.saveConfigButton.clicked.connect(self.save_config_file)
        self.saveResultsButton.clicked.connect(self.save_results_file)

        self.shellFilterCheckBox.stateChanged.connect(self.toggle_l_param)

        self.elements = [
            self.runButton,
            self.aboutButton,
            self.saveConfigButton,
            self.chooseInputFileButton,
            self.electronTemperatureComboBox,
            self.label_10,
            self.checkLocalTime,
            self.checkLShell,
            self.radioIgrf,
            self.radioCgm,
            self.shellFilterCheckBox,
            self.shellEdit,
            self.dShellEdit
        ]

        font = QFont('Monospace')
        font.setStyleHint(QFont.TypeWriter)
        self.logListWidget.setFont(font)

        self.show()
        self.directory_name = None

        self.configs = {
            'proxy_host': self.proxyHostEdit,
            'proxy_port': self.proxyPortEdit,
            'point_lat': self.pointLatEdit,
            'point_long': self.pointLongEdit,
            'lat': self.latitudeEdit,
            'long': self.longitudeEdit,
            'dlat': self.dLatEdit,
            'dlong': self.dLongEdit}

        self.load_config_file()

    def toggle_l_param(self):
        [x.setEnabled(self.shellFilterCheckBox.isChecked())
         for x in [self.shellEdit, self.dShellEdit]]

    def save_results_file(self):
        filename, _ = QFileDialog.getSaveFileName()
        if filename:
            ext = '.txt'
            if not filename.endswith(ext):
                filename += ext
            try:
                with open(filename, 'w') as file:
                    file.write(Formats.HEADER + '\n')
                    n = 1
                    for i in range(self.logListWidget.count()):
                        item_text = self.logListWidget.item(i).text() + '\n'
                        if item_text.startswith('#'):
                            file.write('{:<5d} '.format(n) + item_text[6:])
                            n += 1

            except IOError:
                self.show_error('Error writing to file')

    def load_config_file(self):
        config_from_file = dict()

        try:
            with open('config.ini') as file:
                lines = file.readlines()

            for line in lines:
                key, value = [x.strip() for x in line.split('=')]
                config_from_file[key] = value
        except IOError:
            pass

        for config in config_from_file:
            self.configs[config].setText(config_from_file[config])

    def save_config_file(self):
        s = ''
        for config in self.configs:

            val = self.configs[config].text().strip()
            if val:
                s += '{} = {}\n'.format(config, val)

        try:
            with open('config.ini', 'w') as file:
                file.write(s)
        except IOError:
            self.show_error('Error writing to file')

    def run(self):
        configuration = self.read_configuration()
        if configuration is not None:
            self.logListWidget.clear()
            [e.setEnabled(False) for e in self.elements]
            self.terminateButton.setEnabled(True)
            self.thread = RunThread(configuration)
            self.thread.finished.connect(self.finished)
            self.thread.log.connect(self.log)
            self.thread.start()

    def terminate(self):
        self.thread.terminate()
        self.terminateButton.setEnabled(False)
        [e.setEnabled(True) for e in self.elements]

    def choose_file(self):
        directory_name = str(QFileDialog.getExistingDirectory(self))
        if directory_name:
            self.directory_name = directory_name
            self.inputFileNameEdit.setText(directory_name)

    @pyqtSlot(bool)
    def finished(self, status):
        self.logListWidget.addItem('OK' if status else 'Error')
        time = datetime.now().replace(microsecond=0)
        self.logListWidget.addItem('{}. Processing ended.'.format(time))
        self.terminate()

    @pyqtSlot(str)
    def log(self, text):
        self.logListWidget.addItem(text)

    def read_configuration(self):
        result = dict()
        success = True
        result['directory_name'] = self.directory_name
        if not result['directory_name']:
            success = False

        try:
            result['dmsp_lat'] = float(self.latitudeEdit.text())
            result['dmsp_long'] = float(self.longitudeEdit.text())
            result['dmsp_dlat'] = float(self.dLatEdit.text())
            result['dmsp_dlong'] = float(self.dLongEdit.text())
            result['point_lat'] = float(self.pointLatEdit.text())
            result['point_long'] = float(self.pointLongEdit.text())
            if result['dmsp_long'] > 180.0:
                result['dmsp_long'] -= 360.0
            if result['point_long'] > 180.0:
                result['point_long'] -= 360.0
            if result['dmsp_dlat'] < 0 or result['dmsp_dlong'] < 0:
                success = False
            if self.shellFilterCheckBox.isChecked():
                result['l_shell_set'] = float(self.shellEdit.text())
                result['dl_shell_set'] = float(self.dShellEdit.text())
                if result['l_shell_set'] < 0 or result['dl_shell_set'] < 0:
                    success = False
        except ValueError:
            success = False

        result['proxy_host'] = self.proxyHostEdit.text().strip()
        result['proxy_port'] = self.proxyPortEdit.text().strip()
        if result['proxy_port']:
            try:
                result['proxy_port'] = int(result['proxy_port'])
            except ValueError:
                success = False

        result['cgm'] = self.radioCgm.isChecked()

        if not success:
            self.show_error('Input parameters are incorrect.')

        return result if success else None

    def show_error(self, message):
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Critical)
        msg.setText(message)
        msg.setWindowTitle('Error')
        msg.show()
        msg.exec_()

    def show_about(self):
        about = (
            '\n\n'
            '© 2019-2020 Oleksandr Bogomaz'
            '\n'
            'o.v.bogomaz1985@gmail.com')

        msg = QMessageBox()
        msg.setIcon(QMessageBox.Information)
        msg.setText(self.program_name + about)
        msg.setWindowTitle('About')
        msg.show()
        msg.exec_()


class RunThread(QThread):

    finished = pyqtSignal(bool)
    log = pyqtSignal(str)

    def __init__(self, configuration):
        QThread.__init__(self)
        self.configuration = configuration
        self.isActive = True

    def run(self):
        if self.isActive:
            time = datetime.now().replace(microsecond=0)
            self.log.emit('{}. Processing started.'.format(time))
            directory_name = self.configuration['directory_name']

        files = FileList.get(directory_name) if self.isActive else []

        for filename in files:

            if self.isActive:
                self.log.emit(
                    'Reading \'{}\' from \'{}\'...'.format(
                        filename, directory_name))
                data = self.read_input_file(directory_name + '/' + filename)
                if data is None or not data:
                    self.log.emit('No data available in file.')
                    continue

            if self.isActive:
                data = self.filter(data, self.configuration)
                num = len(data)
                if num > 1:
                    self.log.emit('{} passes were found.'.format(num))
                elif num == 1:
                    self.log.emit('1 pass was found.')
                else:
                    self.log.emit('No passes were found.')
                    continue

            if self.isActive:
                proxy_host = self.configuration['proxy_host']
                proxy_port = self.configuration['proxy_port']
                proxy = {'proxy_host': proxy_host,
                         'proxy_port': proxy_port} if proxy_host else None
                iri = IriModelAccess(proxy)
                igrf = IgrfModelAccess(proxy)

            if self.isActive:
                self.log.emit(Formats.HEADER)

            n = 0
            for d in data:

                mlt = None
                date = d['date']
                l_shell = -1

                if wnd.checkLocalTime.isChecked():

                    if self.isActive:
                        try:
                            print('Req. 1')
                            mlt = float(
                                iri.get_data(
                                    date, d['lat'], d['long'], 3, False)[0])
                        except ValueError:
                            self.finished.emit(False)
                            return

                        if mlt is None:
                            self.finished.emit(False)
                            return

                    if self.isActive:
                        print('Req. 2')
                        iri_result = iri.get_data_cached(
                            date,
                            self.configuration['point_lat'],
                            self.configuration['point_long'], 3)

                        if iri_result[0]:
                            try:
                                times = [float(x) for x in iri_result]
                            except ValueError:
                                self.finished.emit(False)
                                return

                            delta = float('inf')
                            k = 0
                            for i, v in enumerate(times):
                                if abs(v-mlt) < delta:
                                    k = i
                                    delta = abs(v-mlt)
                            kt = k*0.025

                            date_out = datetime(
                                date.year, date.month, date.day)
                            date_out += timedelta(seconds=int(kt*3600.0))

                            delta = date_out - date
                            if abs(delta.total_seconds()) > 12*60*60:
                                if delta.total_seconds() > 0:
                                    date_out += timedelta(days=-1)
                                else:
                                    date_out += timedelta(days=1)
                            date_out = date_out.isoformat()
                        else:
                            kt = -1
                            date_out = '{:>20s}'.format('-1')

                else:
                    mlt = -1
                    kt = -1
                    date_out = '{:>20s}'.format('-1')

                if wnd.checkLShell.isChecked():
                    if self.isActive:
                        cgm = self.configuration['cgm']
                        l_shell = float(
                            igrf.get_data(
                                date.year, d['lat'], d['long'], d['alt'], 1, cgm=cgm)[0])

                if self.isActive:

                    out_str = Formats.ROW_FORMAT.format(
                        n+1,
                        d['sat_id'],
                        d['lat'], d['long'],
                        d['alt'],
                        d['ti'], d['te'],
                        d['ne'],
                        d['po'],
                        d['ph'], d['phe'],
                        d['rpa'], d['idm'],
                        date.replace(microsecond=0).isoformat(),
                        date.hour + date.minute / 60.0 + date.second/3600.0,
                        d['mlt'],
                        mlt,
                        kt,
                        date_out,
                        l_shell
                    )

                if self.isActive:
                    needFiltering = wnd.shellFilterCheckBox.isChecked()
                    if needFiltering and l_shell > 0:
                        l_shell_set = self.configuration['l_shell_set']
                        dl_shell_set = self.configuration['dl_shell_set']
                        if abs(l_shell_set - l_shell) < dl_shell_set:
                            self.log.emit(out_str)
                            n += 1
                    elif not needFiltering or l_shell < 0:
                        self.log.emit(out_str)
                        n += 1

        self.finished.emit(True)

    def terminate(self):
        self.isActive = False

    def __read_hdf5_file(self, filename):

        data = []

        with h5py.File(filename, 'r') as file:
            main_table = file['Data/Table Layout']
            columns = main_table.dtype.fields.keys()
            nrows = len(main_table)
            #print(filename, columns, nrows)

            years = main_table[:, 'year']
            months = main_table[:, 'month']
            days = main_table[:, 'day']

            hours = main_table[:, 'hour']
            mins = main_table[:, 'min']
            secs = main_table[:, 'sec']

            lats = main_table[:, 'gdlat']
            lons = main_table[:, 'glon']

            alts = main_table[:, 'gdalt']

            tis = list(main_table[:, 'ti']) if 'ti' in columns else [-1]*nrows
            tes = list(main_table[:, 'te']) if 'te' in columns else [-1]*nrows
            nes = list(main_table[:, 'ne']) if 'ne' in columns else (
                list(main_table[:, 'ni']) if 'ni' in columns else [-1]*nrows)

            sat_ids = list(main_table[:, 'sat_id']) if 'sat_id' in columns else (
                [path.basename(filename)[16:18]]*nrows if path.basename(filename).startswith('dms_ut_') else [-1]*nrows)
            mlts = list(main_table[:, 'mlt']
                        ) if 'mlt' in columns else [-1]*nrows
            pos = list(main_table[:, 'po+']
                       ) if 'po+' in columns else [-1]*nrows
            phs = list(main_table[:, 'ph+']
                       ) if 'ph+' in columns else [-1]*nrows
            phes = list(main_table[:, 'phe+']
                        ) if 'phe+' in columns else [-1]*nrows
            rpas = list(main_table[:, 'rpa_flag_ut']
                        ) if 'rpa_flag_ut' in columns else [-1]*nrows
            idms = list(main_table[:, 'idm_flag_ut']
                        ) if 'idm_flag_ut' in columns else [-1]*nrows

            for x in [tis, tes, nes, sat_ids, mlts, pos, phs, phes, rpas, idms]:
                for i, e in enumerate(x):
                    if str(e) == 'nan':
                        x[i] = -1

            dates = [datetime(
                years[i],
                months[i],
                days[i],
                hours[i],
                mins[i],
                secs[i]) for i in range(nrows)]

            for i in range(nrows):
                data.append({'date': dates[i],
                             'ti': tis[i],
                             'te': tes[i],
                             'ne': nes[i],
                             'lat': lats[i],
                             'long': lons[i],
                             'alt': alts[i],
                             'sat_id': str(sat_ids[i]),
                             'mlt': mlts[i],
                             'po': float(pos[i]),
                             'ph': float(phs[i]),
                             'phe': float(phes[i]),
                             'rpa': rpas[i],
                             'idm': idms[i],
                             })
        return data

    def __read_txt_file(self, filename):

        data = []

        if filename.endswith('.txt.gz'):
            with gzip.open(filename, 'r') as file:
                lines = [str(line)[2:-4] for line in file.readlines()]

        elif filename.endswith('.txt'):
            with open(filename, 'r') as file:
                lines = file.readlines()

        else:
            return data

        header = lines[0].split()

        try:
            year_pos = header.index('YEAR')
            month_pos = header.index('MONTH')
            day_pos = header.index('DAY')
            hour_pos = header.index('HOUR')
            min_pos = header.index('MIN')
            sec_pos = header.index('SEC')
        except ValueError:
            return None

        def pos_normalize(name):
            try:
                pos = header.index(name)
            except ValueError:
                pos = -1
            return pos

        lat_pos = pos_normalize('GDLAT')
        long_pos = pos_normalize('GLON')
        sat_id_pos = pos_normalize('SAT_ID')
        mlt_pos = pos_normalize('MLT')
        ti_pos = pos_normalize('TI')
        te_pos = pos_normalize('TE')
        ne_pos = pos_normalize('NE')
        if ne_pos == -1:
            ne_pos = pos_normalize('NI')
        alt_pos = pos_normalize('GDALT')
        po_pos = pos_normalize('PO+')
        ph_pos = pos_normalize('PH+')
        phe_pos = pos_normalize('PHE+')
        rpa_pos = pos_normalize('RPA_FLAG_')
        idm_pos = pos_normalize('IDM_FLAG_')

        is_corrected = False

        for line in lines[1:]:
            values = line.split()

            if not is_corrected:
                if len(header) > len(values):
                    lat_pos -= 1
                    long_pos -= 1
                    sat_id_pos -= 1
                    mlt_pos -= 1
                    ti_pos -= 1
                    te_pos -= 1
                    ne_pos -= 1
                    alt_pos -= 1
                    po_pos -= 1
                    ph_pos -= 1
                    phe_pos -= 1
                    rpa_pos -= 1
                    idm_pos -= 1
                is_corrected = True

            date = datetime(int(values[year_pos]), int(values[month_pos]),
                            int(values[day_pos]), int(values[hour_pos]),
                            int(values[min_pos]), int(values[sec_pos]))

            def param_normalize(pos):
                try:
                    result = float(
                        values[pos] if values[pos] != 'nan' else -1
                    ) if pos > 0 else -1
                except ValueError:
                    result = -1
                return result

            ti = param_normalize(ti_pos)
            te = param_normalize(te_pos)
            ne = param_normalize(ne_pos)
            mlt = param_normalize(mlt_pos)
            alt = param_normalize(alt_pos)
            po = param_normalize(po_pos)
            ph = param_normalize(ph_pos)
            phe = param_normalize(phe_pos)
            rpa = param_normalize(rpa_pos)
            idm = param_normalize(idm_pos)

            data.append({'date': date,
                         'sat_id': str(int(
                             values[sat_id_pos]
                         ) if sat_id_pos > 0 else (path.basename(filename)[16:18] if path.basename(filename).startswith('dms_ut_') else -1)),
                         'ti': ti,
                         'te': te,
                         'ne': ne,
                         'mlt': mlt,
                         'po': po,
                         'ph': ph,
                         'phe': phe,
                         'rpa': int(rpa),
                         'idm': int(idm),
                         'lat': float(values[lat_pos]),
                         'long': float(values[long_pos]),
                         'alt': alt,
                         })
        return data

    def __read_cdf_file(self, filename):

        data = []

        te_name = wnd.electronTemperatureComboBox.currentText()
        ne_name = 'Density'
        cdf = CDF(filename)

        z_var = 'zVariables'
        timestamps, latitudes, longitudes, heights, densities, temperatures = (
            cdf.varget('Timestamp'),
            cdf.varget('Latitude'),
            cdf.varget('Longitude'),
            cdf.varget('Height'),
            cdf.varget(ne_name) if ne_name in cdf.cdf_info()[z_var] else None,
            cdf.varget(te_name) if te_name in cdf.cdf_info()[z_var] else None)

        dates = [datetime.fromtimestamp(t, timezone.utc).replace(tzinfo=None)
                 for t in cdfepoch.unixtime(timestamps)]

        basename = path.basename(filename)
        sat_id = basename[11:12] if basename.startswith('SW_EXTD_EFI') else -1

        nrows = len(dates)
        for i in range(nrows):
            data.append({'date': dates[i],
                         'ti': -1,
                         'te': temperatures[i] if temperatures is not None else -1,
                         'ne': densities[i] if densities is not None else -1,
                         'lat': latitudes[i],
                         'long': longitudes[i],
                         'alt': heights[i],
                         'sat_id': sat_id,
                         'mlt': -1,
                         'po': -1,
                         'ph': -1,
                         'phe': -1,
                         'rpa': -1,
                         'idm': -1,
                         })
        return data

    def read_input_file(self, filename):
        if filename.endswith('.hdf5'):
            return self.__read_hdf5_file(filename)
        elif filename.endswith('.txt') or filename.endswith('.txt.gz'):
            return self.__read_txt_file(filename)
        elif filename.endswith('.cdf'):
            return self.__read_cdf_file(filename)

    def filter(self, data, configuration):

        sat_lat = configuration['dmsp_lat']
        sat_lon = configuration['dmsp_long']
        sat_dlat = configuration['dmsp_dlat']
        sat_dlon = configuration['dmsp_dlong']

        lat_m = sat_lat - sat_dlat
        lat_m = -90 if lat_m < -90 else lat_m
        lat_p = sat_lat + sat_dlat
        lat_p = 90 if lat_m > 90 else lat_p

        lon_m = sat_lon - sat_dlon
        lon_m += 360 if lon_m < -180 else 0

        lon_p = sat_lon + sat_dlon
        lon_p -= 360 if lon_p > 180 else 0

        if lon_p-lon_m == 2*sat_dlon:
            lon_ranges = [(lon_m, lon_p)]
        elif sat_dlon == 180:
            lon_ranges = [(-180, 180)]
        else:
            lon_ranges = [(-180, lon_p), (lon_m, 180)]

        result = []
        for d in data:
            lat_check = d['lat'] >= lat_m and d['lat'] <= lat_p
            lon_check = d['long'] >= lon_ranges[0][0] and d['long'] <= lon_ranges[0][1] if len(lon_ranges) == 1 else \
                d['long'] >= lon_ranges[0][0] and d['long'] <= lon_ranges[0][1] or \
                d['long'] >= lon_ranges[1][0] and d['long'] <= lon_ranges[1][1]
            if lat_check and lon_check:
                result.append(d)

        return result


class IriModelAccess:
    def __init__(self, proxy=None):

        if proxy is not None:
            self.proxies = {
                'https': '{}:{}'.format(
                    proxy['proxy_host'],
                    proxy['proxy_port'])
            }

        self.url = ('https://ccmc.gsfc.nasa.gov'
                    '/cgi-bin/modelweb/models/vitmo_model.cgi')

        self.cache = dict()

    @staticmethod
    def __calc_hash(date, latitude, longitude, all_day):
        return '{:04d}-{:02d}-{:02d}_{}_{}_{}'.format(
            date.year, date.month, date.day, latitude, longitude, all_day)

    def __load_cache(self, param_hash):
        return self.cache[param_hash] if param_hash in self.cache else None

    def __save_cache(self, param_hash, data):
        keys = self.cache.keys()
        n = len(keys)
        if n > 200:
            p = randint(0, n-1)
            del self.cache[keys[p]]
        self.cache[param_hash] = data

    def get_data_cached(self, date, latitude, longitude, n, all_day=True):

        longitude = float(longitude)
        if longitude < 0:
            longitude += 360.0

        param_hash = IriModelAccess.__calc_hash(
            date, latitude, longitude, all_day)
        data = self.__load_cache(param_hash)
        if data is None:
            data = self.get_data(date, latitude, longitude, n, all_day)
            self.__save_cache(param_hash, data)
        else:
            print('Data (hash: {}) are loaded from cache.'.format(param_hash))
        return data

    def get_data(self, date, latitude, longitude, n, all_day=True):

        day = str(date.day)
        month = str(date.month)
        year = str(date.year)

        if all_day:
            start = '0'
            stop = '23.97'
        else:
            start = str(date.hour+date.minute/60.0+date.second/3600.0)
            stop = start

        step = '0.025'

        longitude = float(longitude)
        if longitude < 0:
            longitude += 360.0

        parameters = {
            'model': 'iri2016',
            'format': '0',  # 0 - list
            'year': year,
            'month': month,
            'day': day,
            'time_flag': '0',  # universal
            'hour': '0',
            'geo_flag': '0.',  # geographic
            'latitude': str(latitude),
            'longitude': str(longitude),
            'height': '2000',
            'profile': '8',  # hour profile
            'start': start,
            'stop': stop,
            'step': step,
            'vars': ['16']  # MLT
        }

        headers = {
            'Connection': 'close',
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_1) '
                          'AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/39.0.2171.95 Safari/537.36'
        }

        def try_request(timeout):
            result = ''
            sleep(timeout)
            try:
                result = requests.post(
                    self.url,
                    data=parameters,
                    proxies=self.proxies if 'proxies' in vars(self) else None,
                    headers=headers)
            except requests.exceptions.RequestException:
                if timeout > 60:
                    return None
                timeout *= 2
                print('Error. New request timeout: ' + str(timeout) + ' s')
                result = try_request(timeout)
            return result

        r = try_request(1)
        #print(r.text, file=open('out.html', 'w'))
        try:
            start_pos = r.text.index('     1') + 7
            end_pos = r.text.index('</pre>')
            lines = r.text[start_pos: end_pos].strip()
        except ValueError:
            if n > 60:
                return None
            else:
                n *= 2
                print('Bad data. Retrying after ' + str(n) + ' s')
                sleep(n)
                return self.get_data_cached(
                    date, latitude, longitude, n, all_day)

        values = lines.split('\n')
        return values


class IgrfModelAccess:
    def __init__(self, proxy=None):

        self.proxies = None
        if proxy is not None:
            self.proxies = {
                'https': '{}:{}'.format(
                    proxy['proxy_host'],
                    proxy['proxy_port'])
            }

        self.url_cgm = ('https://omniweb.gsfc.nasa.gov'
                        '/cgi/vitmo/cgm_model.cgi')

        self.url_igrf = ('https://ccmc.gsfc.nasa.gov'
                         '/cgi-bin/modelweb/models/vitmo_model.cgi')

    def get_data(self, year, lat, lon, height, n=1, cgm=False):

        parameters = {
            'model': 'cgm' if cgm else 'igrf',
            'format': '0',  # 0 - list
            'year': str(year),
            'height': height,
            'latitude': lat,
            'longitude': lon,
            'profile': '1' if cgm else '3',  # Height profile
            'start': '{:.1f}'.format(height),
            'stop': '{:.1f}'.format(height),
            'step': '{:.1f}'.format(10.0),
            'vars': ['42'] if cgm else ['12']  # L_value
        }

        headers = {
            'Connection': 'close',
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_1) '
                          'AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/39.0.2171.95 Safari/537.36'
        }

        def try_request(timeout):
            result = ''
            sleep(timeout)
            try:
                result = requests.post(
                    self.url_cgm if cgm else self.url_igrf,
                    data=parameters,
                    proxies=self.proxies,
                    headers=headers)
            except requests.exceptions.RequestException:
                if timeout > 60:
                    return None
                timeout *= 2
                print('Error. New request timeout: ' + str(timeout) + ' s')
                result = try_request(timeout)
            return result

        r = try_request(1)
        try:
            start_pos = (r.text.index('      1') +
                         7) if cgm else (r.text.index('        1') + 9)
            end_pos = r.text.index(
                '<hr></pre><HR>') if cgm else r.text.index('</pre><HR>')
            lines = r.text[start_pos: end_pos].strip()
        except ValueError:
            if n > 60:
                return None
            else:
                n *= 2
                print('Bad data. Retrying after ' + str(n) + ' s')
                sleep(n)
                return self.get_data(year, lat, height, n)

        values = [[float(x) for x in line.split()]
                  for line in lines.split('\n')]
        return values[0]


if __name__ == '__main__':
    app = QApplication(sys.argv)
    wnd = MainWnd()
    sys.exit(app.exec_())
