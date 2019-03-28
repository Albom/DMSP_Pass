import sys
from math import modf
from time import sleep
from datetime import datetime, timedelta
import requests
import gzip
from PyQt5 import uic
from PyQt5.QtGui import QFont
from PyQt5.QtCore import QThread, pyqtSignal, pyqtSlot, Qt
from PyQt5.QtWidgets import QApplication, \
    QMainWindow, QFileDialog, QMessageBox
import warnings
with warnings.catch_warnings():
    warnings.filterwarnings('ignore', category=FutureWarning)
    import h5py


class Formats:

        __HEADER_FORMAT = (
            '{:<6s}  '  # n
            '{:>2s}  '  # sat_id
            '{:>7s}  {:>7s}  '  # lat, long
            '{:>6s}  {:>6s}  '  # ti, te
            '{:>12s}  '  # ne
            '{:>10s}  '  # PO+
            '{:>3s}  {:>3s}  '  # RPA, IDM
            '{}    '  # date for DMSP
            '{:>8s}    '  # mlt
            '{:>8s}    '  # mlt from IRI
            '{:>8s}    '  # UT for Point
            '{}'  # date for Point
            )

        HEADER = __HEADER_FORMAT.format(
            'i',
            'id',
            'lat', 'lon',
            'ti', 'te',
            'ne',
            'po+',
            'rpa', 'idm',
            '          date_dmsp',
            'mlt_dmsp',
            'mlt_iri',
            'ut_point',
            '         date_point'
            )


class MainWnd(QMainWindow):

    def __init__(self):
        super().__init__()
        uic.loadUi('./ui/MainWnd.ui', self)
        self.showMaximized()

        self.runButton.clicked.connect(self.run)
        self.terminateButton.clicked.connect(self.terminate)
        self.chooseInputFileButton.clicked.connect(self.choose_file)
        self.saveConfigButton.clicked.connect(self.save_config_file)
        self.saveResultsButton.clicked.connect(self.save_results_file)

        font = QFont("Monospace")
        font.setStyleHint(QFont.TypeWriter)
        self.logListWidget.setFont(font)

        self.show()
        self.input_file_name = None

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

    def save_results_file(self):
        filename, _ = QFileDialog.getSaveFileName()
        if filename:
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
            self.runButton.setEnabled(False)
            self.aboutButton.setEnabled(False)
            self.saveConfigButton.setEnabled(False)
            self.chooseInputFileButton.setEnabled(False)
            self.terminateButton.setEnabled(True)
            self.thread = RunThread(configuration)
            self.thread.finished.connect(self.finished)
            self.thread.log.connect(self.log)
            self.thread.start()

    def terminate(self):
        self.thread.terminate()
        self.terminateButton.setEnabled(False)
        self.runButton.setEnabled(True)
        self.aboutButton.setEnabled(True)
        self.saveConfigButton.setEnabled(True)
        self.chooseInputFileButton.setEnabled(True)

    def choose_file(self):
        filename, _ = QFileDialog.getOpenFileName()
        if filename:
            self.input_file_name = filename
            self.inputFileNameEdit.setText(filename.split('/')[-1])

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
        result['filename'] = self.input_file_name
        if not result['filename']:
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
        except ValueError:
            success = False

        result['proxy_host'] = self.proxyHostEdit.text().strip()
        result['proxy_port'] = self.proxyPortEdit.text().strip()
        if result['proxy_port']:
            try:
                result['proxy_port'] = int(result['proxy_port'])
            except ValueError:
                success = False

        if not success:
            self.show_error('Input parameters are incorrect.')

        return result if success else None

    def show_error(self, message):
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Critical)
        msg.setText(message)
        msg.setWindowTitle("Error")
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
            filename = self.configuration['filename']
            self.log.emit('Reading \'{}\'...'.format(filename))
            data = self.read_input_file(filename)
            if data is None:
                self.finished.emit(False)
                return

        if self.isActive:
            data = self.filter(data, self.configuration)
            num = len(data)
            if num > 1:
                self.log.emit('{} passes were found.'.format(num))
            elif num == 1:
                self.log.emit('1 pass was found.')
            else:
                self.log.emit('No passes were found.')
                self.finished.emit(False)
                return

        if self.isActive:
            proxy_host = self.configuration['proxy_host']
            proxy_port = self.configuration['proxy_port']
            iri = IriModelAccess(
                {'proxy_host': proxy_host, 'proxy_port': proxy_port})

        if self.isActive:

            self.log.emit(Formats.HEADER)

        for n, d in enumerate(data):
            mlt = None
            date = d['date']

            if self.isActive:
                mlt = float(
                    iri.get_data(date, d['lat'], d['long'], 0, False)[0])

            if mlt is None:
                self.finished.emit(False)
                return

            if self.isActive:
                times = [float(x)
                         for x in iri.get_data(
                             date,
                             self.configuration['point_lat'],
                             self.configuration['point_long'], 1)]

                delta = float('inf')
                k = 0
                for i, v in enumerate(times):
                    if abs(v-mlt) < delta:
                        k = i
                        delta = abs(v-mlt)
                kt = k*0.025

            if self.isActive:
                date_out = datetime(date.year, date.month, date.day)
                date_out += timedelta(seconds=int(kt*3600.0))

                delta = date_out - date
                if abs(delta.total_seconds()) > 12*60*60:
                    if delta.total_seconds() > 0:
                        date_out += timedelta(days=-1)
                    else:
                        date_out += timedelta(days=1)

            if self.isActive:

                format = (
                    '#{:<5d}  '  # n
                    '{:2d}  '  # sat_id
                    '{:7.2f}  {:7.2f}  '  # lat, long
                    '{:6.1f}  {:6.1f}  '  # ti, te
                    '{:12.5e}  '  # ne
                    '{:10.3e}  '  # PO+
                    '{:3d}  {:3d}  '  # RPA, IDM
                    '{}    '  # date for DMSP
                    '{:8.2f}    '  # mlt
                    '{:8.2f}    '  # mlt from IRI
                    '{:8.3f}    '  # UT for Point
                    '{}'  # date for Point
                    )
                
                out_str = format.format(
                    n+1,
                    d['sat_id'],
                    d['lat'], d['long'],
                    d['ti'], d['te'],
                    d['ne'],
                    d['po'],
                    d['rpa'], d['idm'],
                    str(date.replace(microsecond=0)).replace(' ', 'T'),
                    d['mlt'],
                    mlt,
                    kt,
                    str(date_out).replace(' ', 'T'))

            if self.isActive:
                self.log.emit(out_str)

        self.finished.emit(True)

    def terminate(self):
        self.isActive = False

    def __read_hdf5_file(self, filename):

        data = []

        with h5py.File(filename, 'r') as file:
            main_table = file['Data/Table Layout']
            columns = main_table.dtype.fields.keys()
            nrows = len(main_table)

            years = main_table[:, 'year']
            months = main_table[:, 'month']
            days = main_table[:, 'day']

            hours = main_table[:, 'hour']
            mins = main_table[:, 'min']
            secs = main_table[:, 'sec']

            lats = main_table[:, 'gdlat']
            lons = main_table[:, 'glon']

            tis = main_table[:, 'ti'] if 'ti' in columns else [-1]*nrows
            tes = main_table[:, 'te'] if 'te' in columns else [-1]*nrows
            nes = main_table[:, 'ne'] if 'ne' in columns else [-1]*nrows

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
                             'lat': lats[i],
                             'long': lons[i],
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
            lat_pos = header.index('GDLAT')
            long_pos = header.index('GLON')
        except ValueError:
            return None

        def pos_normalize(name):
            try:
                pos = header.index(name)
            except ValueError:
                pos = -1
            return pos

        sat_id_pos = pos_normalize('SAT_ID')
        mlt_pos = pos_normalize('MLT')
        ti_pos = pos_normalize('TI')
        te_pos = pos_normalize('TE')
        ne_pos = pos_normalize('NE')
        alt_pos = pos_normalize('GDALT')
        po_pos = pos_normalize('PO+')
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
                        ) if pos != -1 else -1
                except ValueError:
                    result = -1
                return result

            ti = param_normalize(ti_pos)
            te = param_normalize(te_pos)
            ne = param_normalize(ne_pos)
            mlt = param_normalize(mlt_pos)
            alt = param_normalize(alt_pos)
            po = param_normalize(po_pos)
            rpa = param_normalize(rpa_pos)
            idm = param_normalize(idm_pos)

            data.append({'date': date,
                         'sat_id': int(
                            values[sat_id_pos]
                            ) if sat_id_pos != -1 else -1,
                         'ti': ti,
                         'te': te,
                         'ne': ne,
                         'mlt': mlt,
                         'po': po,
                         'rpa': int(
                            values[rpa_pos] if values[rpa_pos] != 'nan' else -1
                            ) if rpa_pos != -1 else -1,
                         'idm': int(
                            values[idm_pos] if values[idm_pos] != 'nan' else -1
                            ) if idm_pos != -1 else -1,
                         'lat': float(values[lat_pos]),
                         'long': float(values[long_pos]),
                         })
        return data

    def read_input_file(self, filename):
        if filename.endswith('.hdf5'):
            return self.__read_hdf5_file(filename)
        else:
            return self.__read_txt_file(filename)

    def filter(self, data, configuration):

        dmsp_lat = configuration['dmsp_lat']
        dmsp_long = configuration['dmsp_long']
        dmsp_dlat = configuration['dmsp_dlat']
        dmsp_dlong = configuration['dmsp_dlong']

        lat_m = dmsp_lat - dmsp_dlat
        lat_m = -90 if lat_m < -90 else lat_m
        lat_p = dmsp_lat + dmsp_dlat
        lat_p = 90 if lat_m > 90 else lat_p

        long_m = dmsp_long - dmsp_dlong
        long_m += 360 if long_m < -180 else 0
        long_p = dmsp_long + dmsp_dlong
        long_p -= 360 if long_m > 180 else 0

        result = []
        for d in data:
            lat_check = d['lat'] >= lat_m and d['lat'] <= lat_p
            long_check = d['long'] >= long_m and d['long'] <= long_p
            if lat_check and long_check:
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
            try:
                result = requests.post(
                    self.url,
                    data=parameters,
                    proxies=self.proxies,
                    headers=headers)
            except requests.exceptions.RequestException:
                if timeout > 10:
                    return None
                timeout += 1
                print('Request timeout: ' + str(timeout) + ' s')
                sleep(timeout)
                result = try_request(timeout)
            return result

        r = try_request(0)

        try:
            start_pos = r.text.index('     1') + 7
            end_pos = r.text.index('</pre>')
            lines = r.text[start_pos: end_pos].strip()
        except ValueError:
            if n > 10:
                return None
            else:
                n += 1
                print('Bad data. Retrying after ' + str(n) + ' s')
                sleep(n)
                return self.get_data(date, latitude, longitude, n, all_day)

        values = lines.split('\n')
        return values


if __name__ == '__main__':
    app = QApplication(sys.argv)
    wnd = MainWnd()
    sys.exit(app.exec_())