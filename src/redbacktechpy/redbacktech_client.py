"""Python API for Redback Tech Systems"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Any
import re
from math import sqrt
import uuid
import asyncio
import logging
from aiohttp import ClientResponse, ClientSession
from bs4 import BeautifulSoup

from .constants import (
    BaseUrl,
    Endpoint,
    Header,
    InverterOperationType,
    TIMEOUT,
    AUTH_ERROR_CODES,
    DEVICEINFOREFRESH,
    INVERTER_MODES,
    INVERTER_PORTAL_MODES,
    OAUTH_GRANT_TYPE,
    OAUTH_SCOPE,
)

from .model import (
    OpEnvelopes,
    RedbackTechData,
    RedbackEntitys,
    DeviceInfo,
    Buttons,
    Selects,
    Numbers,
    ScheduleInfo,
    ScheduleDateTime,
    Text,
)
from .exceptions import (
        AuthError,
        RedbackTechClientError,
)

LOGGER = logging.getLogger(__name__)

class RedbackTechClient:
    """Redback Tech Client"""

    def __init__(self, client_id: str, client_secret:str, portal_email: str, portal_password: str, session1: ClientSession | None = None, session2: ClientSession | None = None, timeout: int = TIMEOUT, include_envelopes=True, debug_logging = False) -> None:
        self.client_id: str = client_id
        self.client_secret: str = client_secret
        self.portal_email: str = portal_email
        self.portal_password: str = portal_password
        self.timeout: int = timeout
        self.serial_numbers: list[str] | None = None
        self._session1: ClientSession = session1 if session1 else ClientSession()
        self._session2: None # ClientSession = session2 if session2 else ClientSession()
        self._include_envelopes: bool = include_envelopes
        self.token: str | None = None
        self.token_type: str | None = None
        self.token_expiration: datetime | None = None
        self._GAFToken: str | None = None
        self._device_info_refresh_time: datetime | None = None
        self._redback_site_ids = []
        self._redback_devices = []
        self._redback_mppt_data = {}
        self._redback_entities = []
        self._redback_device_info = []
        self._redback_buttons = []
        self._redback_numbers = []
        self._redback_selects = []
        self._redback_text = []
        self._redback_schedule_datetime = []
        self._redback_schedules = []
        self._redback_open_env_data = []
        self._redback_site_load = {}
        self._inverter_control_settings = {}
        self._redback_schedule_selected = {}
        self._redback_temp_voltage = {}
        self._redback_active_schedule = {}
        self._serial_numbers = []
        self._dynamic_data = []
        self._response1_data = {}
        self._response1_data_timer ={}
        self._redback_op_env_data = {}
        self._redback_op_env_active = {}
        self._redback_op_env_create_settings = {}
        self._redback_op_env_selected = {}
        
        if debug_logging:
            LOGGER.setLevel(logging.DEBUG)

    async def get_redback_data(self):
        """Get Redback Data."""
        #Check if we need to get a new device list
        await self._create_device_info()
        if self._include_envelopes:
            await self._create_op_env_data()

        op_envelope_data: dict[str, OpEnvelopes] = {}
        text_data: dict[str, Text] = {}
        entity_data: dict[str, RedbackEntitys] = {}
        device_info_data: dict[str, DeviceInfo] = {}
        button_data: dict[str, Buttons] = {}
        selects_data: dict[str, Selects] = {}
        numbers_data: dict[str, Numbers] = {}
        schedules_data: dict[str, ScheduleInfo] = {}
        schedules_datetime_data: dict[str, ScheduleDateTime] = {}

        if self._redback_open_env_data is not None:
            envelope_calendar_list = []
            self._redback_open_env_data.sort(key = lambda x: x['data']['StartAtUtc'])
            for op_env in self._redback_open_env_data:
                op_instance, op_id = await self._handle_op_env(op_env)
                op_envelope_data[op_id] = op_instance
                envelope_calendar_list.append(await self._handle_envelope_calendar(op_env))

        if self._redback_entities is not None:
            for entity in self._redback_entities:
                ent_instance, ent_id = await self._handle_entity(entity)
                entity_data[ent_id] = ent_instance            

        if self._redback_device_info is not None:
            for device in self._redback_device_info:
                device_instance, dev_id = await self._handle_device_info(device)
                device_info_data[dev_id] = device_instance

        if self._redback_buttons is not None:
            for button in self._redback_buttons:
                button_instance, button_id = await self._handle_button(button)
                button_data[button_id] = button_instance

        if self._redback_numbers is not None:
            for number in self._redback_numbers:
                number_instance, number_id = await self._handle_number(number)
                numbers_data[number_id] = number_instance

        if self._redback_text is not None:
            for text in self._redback_text:
                text_instance, text_id = await self._handle_text(text)
                text_data[text_id] = text_instance

        if self._redback_selects is not None:
            for select in self._redback_selects:
                select_instance, select_id = await self._handle_select(select)
                selects_data[select_id] = select_instance

        if self._redback_schedules is not None:
            inverter_calendar_list = []
            self._redback_schedules.sort(key = lambda x: x['start_time_utc'])
            for schedule in self._redback_schedules:
                schedule_instance, schedule_id = await self._handle_schedule(schedule)
                schedules_data[schedule_id] = schedule_instance
                inverter_calendar_list.append(await self._handle_inverter_calendar(schedule))

        if self._redback_schedule_datetime is not None:
            for schedule in self._redback_schedule_datetime:
                schedule_instance, schedule_id = await self._handle_schedule_datetime(schedule)
                schedules_datetime_data[schedule_id] = schedule_instance

        return RedbackTechData(
            user_id = self.client_id,
            openvelopes = op_envelope_data,
            text = text_data,
            entities = entity_data,
            devices = device_info_data,
            buttons= button_data,
            numbers= numbers_data,
            selects= selects_data,
            schedules= schedules_data,
            schedules_datetime_data = schedules_datetime_data,
            inverter_calendar = inverter_calendar_list,
            envelope_calendar = envelope_calendar_list
        )

    async def _api_login(self) -> None:
        """Login to Redback API and obtain token."""
        #login_url = f'{BaseUrl.API}{Endpoint.API_AUTH}'
        login_url = f'{BaseUrl.OAUTH}{Endpoint.API_OAUTH}'

        headers = {
            'Content-Type': Header.CONTENT_TYPE,
        }

        #data = b'client_id=' + self.client_id.encode() + b'&client_secret=' + self.client_secret.encode() + '&grant_type=' + OAUTH_GRANT_TYPE + '&scope=' + OAUTH_SCOPE
        data = 'client_id=' + self.client_id + '&client_secret=' + self.client_secret + '&grant_type=' + OAUTH_GRANT_TYPE + '&scope=' + OAUTH_SCOPE

        response = await self._api_post(login_url, headers, data)
        self.token = response['token_type'] + ' '+ response['access_token']
        self.token_type = ['token_type']
        self.token_expiration = datetime.now() + timedelta(seconds=response['expires_in'])
        return

    async def _portal_login(self) -> None:
        """Login to Redback Portal and obtain token."""
        self._session2 = ClientSession() #.cookie_jar.clear()
        login_url = f'{BaseUrl.PORTAL}{Endpoint.PORTAL_LOGIN}'
        response = await self._portal_get(login_url, {}, {})
        await self._get_portal_token(response, 1)
        data={
            "Email": self.portal_email,
            "Password": self.portal_password,
            "__RequestVerificationToken": self._GAFToken
        }

        headers = {
            'Referer': Header.REFERER_UI,
        }

        response = await self._portal_post(login_url, headers, data)
        return

    async def test_api_connection(self) -> dict[str, Any]:
        """Test API connection."""
        await self._check_token()
        if self.token is not None:
            return True
        return False

    async def test_portal_connection(self) -> dict[str, Any]:
        """Test Portal connection."""
        self._GAFToken = None
        await self._portal_login()
        if self._GAFToken is not None:
            await self._session2.close()
            return True
        await self._session2.close()
        return False

    async def delete_inverter_schedule(self, device_id: str, schedule_selector: str) -> dict[str, Any]:
        """Delete inverter schedule."""
        serial_number = None
        schedule_id = None
        if schedule_selector is not None:
            self._redback_schedule_selected.update([(device_id,{'schedule_selector': None})])
            for device in self._redback_device_info:
                if device['identifiers'] == device_id:
                    serial_number = device['serial_number']
                    break
            for schedules in self._redback_schedules:
                if schedules['schedule_selector'] == schedule_selector:
                    schedule_id = schedules['schedule_id']
                    break
            if schedule_id is not None and serial_number is not None:
                await self._check_token()
                headers = {
                    'Authorization': self.token,
                    'Content_type': 'text/json',
                    'accept': 'text/plain'
                }
                await self._api_delete(url=f'{BaseUrl.API}{Endpoint.API_SCHEDULE_DELETE_BY_SERIALNUMBER_SCHEDULEID}{serial_number}' + '/' + schedule_id, headers=headers, data='' )
        return

    async def delete_all_inverter_schedules(self, device_id: str):
        """Delete all inverter schedules."""
        self._redback_schedule_selected.update([(device_id,{'schedule_selector': None})])
        for device in self._redback_device_info:
            if device['identifiers'] == device_id:
                serial_number = device['serial_number']
                break
        headers = {
            'Authorization': self.token,
            'Content_type': 'text/json',
            'accept': 'text/plain'
        }
        for schedule in self._redback_schedules:
            if schedule['serial_number'] == serial_number:
                await self._api_delete(url=f'{BaseUrl.API}{Endpoint.API_SCHEDULE_DELETE_BY_SERIALNUMBER_SCHEDULEID}{serial_number}' + '/' + schedule['schedule_id'], headers=headers, data='' )
        return

    async def create_schedule_service(self, device_id: str, mode: str, power: int, duration: int, start_time: datetime) -> dict[str, Any]:
        """Create schedule service."""
        self._inverter_control_settings.update([(device_id,{'power_setting_mode': mode, 'power_setting_watts': power, 'power_setting_duration': duration, 'start_time': start_time})])
        await self.set_inverter_schedule(device_id)
        return

    async def set_inverter_schedule(self, device_id):
        """Set inverter schedule."""
        for device in self._redback_device_info:
            if device['identifiers'] == device_id:
                serial_number = device['serial_number']
                break
        mode = self._inverter_control_settings[device_id]['power_setting_mode']
        power = self._inverter_control_settings[device_id]['power_setting_watts']
        duration = self._inverter_control_settings[device_id]['power_setting_duration']
        start_time = self._inverter_control_settings[device_id]['start_time']

        ### convert duration to format
        days = int(duration/1440)
        if days < 0:
            days = 0
        hours = int(duration/60)
        minutes = ('00'+str(int(duration - (hours * 60))))[-2:]
        hours = ('00'+str(hours))[-2:]
        duration_str = f'{days}.{hours}:{minutes}:00'

        post_data = {
            'SerialNumber': serial_number,
            'UserNotes': 'Home Assistant Created Inverter Schedule',
            'StartTimeUtc': start_time,
            'Duration': duration_str,
            'DesiredMode': {
                'InverterMode': mode,
                'ArgumentInWatts': int(power)
            }
        }
        headers = {
            'Authorization': self.token,
            'Content_type': 'application/json',
            'accept': 'text/plain'
        }
        await self._check_token()
        await self._api_post_json(f'{BaseUrl.API}{Endpoint.API_SCHEDULE_CREATE_BY_SERIALNUMBER}', headers, post_data)
        return

    async def _get_inverter_mppt_data(self, serial_numbers: str) -> dict[str, Any]:
        """Get inverter MPPT data."""
        await self._portal_login()
        for serial_number in serial_numbers:
            pv_number_panels =[]
            pv_panel_direction =[]
            full_url = f"{BaseUrl.PORTAL}{Endpoint.PORTAL_INSTALLATION_DETAILS}{serial_number}"
            response = await self._portal_get(full_url, {}, {})
            soup = BeautifulSoup(response , features="html.parser")
            form = soup.find("form", id="form")
            pv_size = form.find_all("input",id = re.compile("SolarPanels_[0-9]__PVSize"))
            divs_name = form.find_all("div", {"class" : "form-group rb-selectbox"}) 
            for div in divs_name:
                select = div.find("select")
                if re.compile("SolarPanels_[0-9]__NumberOfPanels").match(select['id']):
                    option = select.find_all("option")
                    for opt in option:
                        if opt.get('selected') == 'selected':
                            pv_number_panels.append(opt.get('value'))
                            break
                if re.compile("SolarPanels_[0-9]__PanelDirection").match(select['id']):
                    option = select.find_all("option")
                    for opt in option:
                        if opt.get('selected') == 'selected':
                            pv_panel_direction.append(opt.get('value'))
                            break
            x=0
            mppt_strings= {}
            while x < len(pv_size):
                data = {}
                data["pv_size"] = pv_size[x].attrs["value"]
                if len(pv_number_panels) >x:
                    data["pv_number_panels"] = pv_number_panels[x]
                if len(pv_panel_direction) >x:
                    data["pv_panel_direction"] = pv_panel_direction[x]
                x=x+1
                mppt_strings['mppt_'+str(x)] = data
            self._redback_mppt_data[serial_number] = mppt_strings
        return

    async def set_inverter_mode_portal(self, device_id: str, mode='Auto', power = 0, mode_override=False):
        """Set inverter mode."""
        LOGGER.debug('Setting inverter mode for %s to %s with power %s', device_id, mode, power)
        for device in self._redback_device_info:
            if device['identifiers'] == device_id+'inv':
                serial_number = device['serial_number']
                ross_version = device['sw_version']
                break
        if mode_override:
            mode = 'Auto'
            power = 0
        else:
            if mode not in INVERTER_PORTAL_MODES:
                mode = 'Auto'
                power = 0
            if power < 0 or power > 10000:
                mode = 'Auto'
                power = 0
        await self._portal_login()
        full_url = f'{BaseUrl.PORTAL}{Endpoint.PORTAL_CONFIGURE}{serial_number}'
        response = await self._portal_get(full_url, {}, {})
        await self._get_portal_token(response, 2)
        headers = {
            'X-Requested-With': Header.X_REQUESTED_WITH,
            'Content-Type': Header.CONTENT_TYPE,
            'Referer': full_url
        }
        data = {
            'SerialNumber':serial_number,
            'AppliedTariffId':'',
            'InverterOperation[Type]':InverterOperationType.SET,
            'InverterOperation[Mode]':mode,
            'InverterOperation[PowerInWatts]':power,
            'InverterOperation[AppliedTarrifId]':'',
            'ProductModelName': '',
            'RossVersion':ross_version,
            '__RequestVerificationToken':self._GAFToken     
        }
        LOGGER.debug('Setting inverter mode data: %s ', data)
        full_url = f'{BaseUrl.PORTAL}{Endpoint.PORTAL_INVERTER_SET}'
        await self._portal_post(full_url, headers, data)
        await self._session2.close()
        return

    async def update_inverter_control_values(self, device_id, data_key, data_value):
        """Update inverter control values."""
        temp = self._inverter_control_settings.get(device_id)
        temp.update([(data_key, data_value)])
        self._inverter_control_settings.update([(device_id, temp)])
        return

    async def reset_inverter_start_time_to_now(self, device_id):
        """Update inverter control values."""
        temp = self._inverter_control_settings.get(device_id)
        temp.update([('start_time', datetime.now(timezone.utc))])
        self._inverter_control_settings.update([(device_id, temp)])
        return    

    async def update_selected_schedule_id(self, device_id, schedule_id: str) -> None:
        """Update selected schedule id."""
        temp = self._redback_schedule_selected.get(device_id)
        temp.update([('schedule_selector', schedule_id)])
        self._redback_schedule_selected.update([(device_id, temp)])
        return

    async def update_selected_op_env_id(self, device_id, op_env_id: str) -> None:
        """Update selected schedule id."""
        temp = self._redback_op_env_selected.get(device_id)
        temp.update([('schedule_selector', op_env_id)])
        self._redback_op_env_selected.update([(device_id, temp)])
        return

    async def update_op_envelope_values(self, device_id, data_key, data_value):
        """Update inverter control values."""
        temp = self._redback_op_env_create_settings.get(device_id)
        temp.update([(data_key, data_value)])
        self._redback_op_env_create_settings.update([(device_id, temp)])
        return

    async def delete_all_envelopes(self, device_id,) -> dict[str, Any]:
        """Delete all envelopes."""
        self._redback_op_env_selected.update([(device_id,{'schedule_selector': None})])
        await self._check_token()
        headers = {
            'Authorization': self.token,
            'Content_type': 'text/json',
            'accept': 'text/plain'
        }
        full_url = f'{BaseUrl.API}{Endpoint.API_OPENVELOPE_DELETE_ALL}'
        await self._api_delete(full_url, headers, '')
        return

    async def delete_op_env_by_id(self, device_id, op_env_id: str) -> dict[str, Any]:
        """Delete op env by id."""
        self._redback_op_env_selected.update([(device_id,{'schedule_selector': None})])
        await self._check_token()
        headers = {
            'Authorization': self.token,
            'Content_type': 'text/json',
            'accept': 'text/plain'
        }
        full_url = f'{BaseUrl.API}{Endpoint.API_OPENVELOPE_BY_EVENTID}{op_env_id}'
        await self._api_delete(full_url, headers, '')
        return

    async def create_op_envelope(self, device_id: str) -> dict[str, Any]:
        """Create op envelope."""
        await self._check_token()
        headers = {
            'Authorization': self.token,
            'Content_type': 'application/json',
            'accept': 'text/plain'
        }
        post_data = self._redback_op_env_create_settings[device_id]
        post_data['EventId'] = post_data['EventId'] + '-' + str(uuid.uuid4())[0:6]
        full_url = f'{BaseUrl.API}{Endpoint.API_OPENVELOPE_CREATE}'
        response = await self._api_post_json(full_url, headers, post_data)
        return response
    
    async def create_operating_envelope(self, event_id: str, start_at_utc , end_at_utc, site_id , max_import_power =0, max_export_power=0, max_discharge_power=0, max_charge_power=0, max_generation_power=0) -> dict[str, Any]:
        """Create op envelope."""
        await self._check_token()
        post_data = {
            'EventId': event_id + '-' + str(uuid.uuid4())[0:6],
            'MaxImportPowerW': max_import_power,
            'MaxExportPowerW': max_export_power,
            'MaxDischargePowerW': max_discharge_power,
            'MaxChargePowerW': max_charge_power,
            'MaxGenerationPowerVA': max_generation_power,
            'StartAtUtc': start_at_utc,
            'EndAtUtc': end_at_utc,
            'SiteId': site_id}
        headers = {
            'Authorization': self.token,
            'Content_type': 'application/json',
            'accept': 'text/plain'
        }
        full_url = f'{BaseUrl.API}{Endpoint.API_OPENVELOPE_CREATE}'
        response = await self._api_post_json(full_url, headers, post_data)
        return response

    async def _create_op_env_data(self):
        """Create Operating Envelope Data."""
        #Create the Device info for Operating Envelopes
        await self._create_device_info_op_env()
        #Create the data set
        self._redback_open_env_data = []
        temp_timenow = datetime.now(timezone.utc)
        for site in self._redback_site_ids:
            device_id = site[-4:] + 'env'
            self._redback_op_env_data.setdefault(site, None)
            self._redback_op_env_active.setdefault(site, None)
            await self._create_op_env_active_entities(data=None, device_id=device_id, site=site)
            await self._create_op_env_number_entities(device_id, site)
            await self._create_op_env_text_entities(device_id, site)
            await self._create_op_env_datetime_entities(device_id, site)
            
            response = await self._get_op_env_by_site(site)
            if response['TotalCount'] > 0:
                self._redback_op_env_data[site] = True
            else:
                self._redback_op_env_data[site] = False
            for data in response['Data']:
                openv_id = data['SiteId'] + '-' + data['EventId']
                data['schedule_selector'] = str((datetime.fromisoformat((data['StartAtUtc']).replace('Z','+00:00'))).astimezone())[:16] +'-' + data['EventId']
                start_at_time = datetime.fromisoformat((data['StartAtUtc']).replace('Z','+00:00'))  # and temp_timenow <= end_time
                data['StartAtUtc'] = start_at_time
                end_at_time = datetime.fromisoformat((data['EndAtUtc']).replace('Z','+00:00')) #and temp_timenow <= end_time
                data['EndAtUtc'] = end_at_time
                if data['ReportedStartUtc'] is not None:
                    data['ReportedStartUtc'] = datetime.fromisoformat((data['ReportedStartUtc']).replace('Z','+00:00'))
                if data['ReportedFinishUtc'] is not None:
                    data['ReportedFinishUtc'] = datetime.fromisoformat((data['ReportedFinishUtc']).replace('Z','+00:00'))
                if start_at_time < temp_timenow  < end_at_time:
                    self._redback_op_env_active[site] = True
                    await self._create_op_env_active_entities(data=data, device_id=device_id, site=site)
                self._redback_open_env_data.append({'openv_id': openv_id, 'data': data})
            await self._create_op_env_select_entities(site, device_id)
            await self._add_selected_op_env_entities(site, device_id)
            await self._create_op_env_status_entities(site, device_id,response['TotalCount'] )
        return

    async def _get_inverter_list(self) -> dict[str, Any]:
        """Get inverter list."""
        serial_numbers = []
        self._redback_site_ids = []
        
        await self._check_token()
        headers = {
            'Authorization': self.token
        }
        full_url = f'{BaseUrl.API}{Endpoint.API_NODES}'
        response = await self._api_get(full_url, headers, {})

        for site in response['Data']:
            self._redback_site_ids.append(site['Id'])
            for node in site['Nodes']:
                if node['Type'] == 'Inverter':
                    serial_numbers.append(node['SerialNumber'])
        return serial_numbers

    async def _get_dynamic_by_serial(self, serial_number: str) -> dict[str, Any]:
        """/Api/v2.21/EnergyData/Dynamic/BySerialNumber/{serialNumber}"""
        await self._check_token()
        headers = {
            'Authorization': self.token,
            'Content_type': 'text/json',
            'accept': 'text/plain'
        }
        full_url = f'{BaseUrl.API}{Endpoint.API_ENERGY_DYNAMIC_BY_SERIAL}{serial_number}'
        response = await self._api_get(full_url, headers, {})
        return response

    async def _get_config_by_serial(self, serial_number: str) -> dict[str, Any]:
        """/Api/v2/Configuration/Configuration/BySerialNumber/{serialNumber}"""
        headers = {
            'Authorization': self.token,
            'Content_type': 'text/json',
            'accept': 'text/plain'
        }
        full_url = f'{BaseUrl.API}{Endpoint.API_CONFIG_BY_SERIAL}{serial_number}'
        response = await self._api_get(full_url, headers, {})
        return response

    async def _get_static_by_serial(self, serial_number: str) -> dict[str, Any]:
        """/Api/v2/EnergyData/Static/BySerialNumber/{serialNumber}"""
        await self._check_token()
        headers = {
            'Authorization': self.token,
            'Content_type': 'text/json',
            'accept': 'text/plain'
        }
        full_url = f'{BaseUrl.API}{Endpoint.API_STATIC_BY_SERIAL}{serial_number}'
        response = await self._api_get(full_url, headers, {})
        return response

    async def _get_op_env_by_site(self, site_id: str) -> dict[str, Any]:
        """/Api/v2/OperatingEnvelope/By/Site/{siteId}"""
        await self._check_token()
        headers = {
            'Authorization': self.token,
            'Content_type': 'text/json',
            'accept': 'text/plain'
        }
        full_url = f'{BaseUrl.API}{Endpoint.API_OPENVELOPE_BY_SITE_ALL}{site_id}'
        response = await self._api_get(full_url, headers, {})
        return response

    async def _get_schedules_by_serial(self, serial_number: str) -> dict[str, Any]:
        """/Api/v2/EnergyData/Static/BySerialNumber/{serialNumber}"""
        await self._check_token()
        headers = {
            'Authorization': self.token,
            'Content_type': 'text/json',
            'accept': 'text/plain'
        }
        full_url = f'{BaseUrl.API}{Endpoint.API_SCHEDULE_BY_SERIALNUMBER}{serial_number}'
        response = await self._api_get(full_url, headers, {})
        return response

    async def _get_config_by_multiple_serial(self, serial_numbers: str | None=None) -> dict[str, Any]:
        """Get config by multiple serial numbers."""
        self._serial_numbers: str = serial_numbers if serial_numbers else self._serial_numbers
        if self._serial_numbers is None:
            self._serial_numbers = await self._get_inverter_list()
        await self._check_token()
        headers = {
            'Authorization': self.token,
            'Content_type': 'text/json',
            'accept': 'text/plain'
        }
        full_url = f'{BaseUrl.API}{Endpoint.API_STATIC_MULTIPLE_BY_SERIAL}'
        response = await self._api_post_json(full_url, headers, self._serial_numbers)
        return response

    async def _get_site_list(self) -> dict[str, Any]:
        """Get site list."""
        site_ids = []
        await self._check_token()
        headers = {
            'Authorization': self.token
        }
        full_url = f'{BaseUrl.API}{Endpoint.API_SITES}'
        response = await self._api_get(full_url, headers, {})
        for site in response['Data']:
            site_ids.append(site)
        return site_ids

    async def close_sessions(self) -> None:
        """Close sessions."""
        await self._session1.close()
        await self._session2.close()
        return True

    async def _create_device_info(self) -> None:
        """Create device info."""
        if await self._check_device_info_refresh():
            self._serial_numbers = await self._get_inverter_list()
            await self._get_inverter_mppt_data(self._serial_numbers)
            self._device_info_refresh_time = datetime.now() + timedelta(seconds=DEVICEINFOREFRESH)
        self._redback_device_info = []
        self._redback_entities = []
        self._redback_schedules = []
        self._redback_numbers = []
        self._redback_selects = []
        self._redback_schedule_datetime = []
        #For each Inverter found prepare the data wanted
        for serial_number in self._serial_numbers:
            self._response1_data.setdefault(serial_number, None)
            self._response1_data_timer.setdefault(serial_number, None)
            if self._response1_data[serial_number] is None:
                self._response1_data[serial_number] = await self._get_static_by_serial(serial_number)
                self._response1_data_timer[serial_number]= datetime.now() + timedelta(seconds=DEVICEINFOREFRESH)
            elif self._response1_data_timer[serial_number] < datetime.now():
                self._response1_data[serial_number] = await self._get_static_by_serial(serial_number)
                self._response1_data_timer[serial_number]= datetime.now() + timedelta(seconds=DEVICEINFOREFRESH)
            response1 = self._response1_data[serial_number]
            response2 = await self._get_dynamic_by_serial(serial_number)
            self._redback_site_load[serial_number]=0
            #process and prepare base data wanted
            await self._convert_responses_to_inverter_entities(response1, response2)
            #If we find a battery attached to the inverter process and prepare additional data wanted
            if response2['Data']['BatterySoCInstantaneous0to1'] is not None:
                soc_data = await self._get_config_by_serial(response1['Data']['Nodes'][0]['StaticData']['Id'])
                await self._convert_responses_to_battery_entities(response1, response2, soc_data)
                await self._create_device_info_battery(response1)
                response3 = await self._get_schedules_by_serial(serial_number)
                await self._convert_responses_to_schedule_entities(response3, response1)
                await self._create_number_entities(response1)
                await self._create_select_entities(response1, response3)
                await self._create_datetime_entities(response1)
                await self._add_selected_schedule(response1)
            await self._add_additional_entities(self._redback_site_load[serial_number], response1)
            await self._create_device_info_inverter(response1)
        return

    async def _handle_device_info(self, device: dict[str, Any]) -> (DeviceInfo, str):
        """Handle device info data."""
        device_instance = DeviceInfo(
            identifiers=device['identifiers'],
            name=device['name'],
            model=device['model'],
            sw_version=device['sw_version'],
            hw_version=device['hw_version'],
            serial_number=device['serial_number'],
        )
        return device_instance, device['identifiers']

    async def _handle_op_env(self, op_env: dict[str, Any]) -> (OpEnvelopes, str):
        """Handle op_env data."""
        data = {
            'id': op_env['openv_id']
        }
        op_env_instance = OpEnvelopes(
            id=data['id'],
            site_id=op_env['data']['SiteId'],
            data=op_env['data']
        )
        return op_env_instance, data['id']

    async def _handle_button(self, device: dict[str, Any]) -> (Buttons, str):
        """Handle button data."""
        data = {
            'id': device['device_id'] + device['entity_name']
        }
        button_instance = Buttons(
            id=data['id'],
            device_serial_number=device['device_id'],
            data=device,
            type=device['device_type']
        )
        return button_instance, data['id']

    async def _handle_number(self, device: dict[str, Any]) -> (Numbers, str):
        """Handle number data."""
        data = {
            'id': device['device_id'] + device['entity_name']
        }
        number_instance = Numbers(
            id=data['id'],
            device_serial_number=device['device_id'],
            data=device,
            type=device['device_type']
        )
        return number_instance, data['id']
    
    async def _handle_text(self, device: dict[str, Any]) -> (Text, str):
        """Handle text data."""
        data = {
            'id': device['device_id'] + device['entity_name']
        }
        text_instance = Text(
            id=data['id'],
            site_id=device['device_id'],
            data=device
        )
        return text_instance, data['id']

    async def _handle_select(self, device: dict[str, Any]) -> (Selects, str):
        """Handle select data."""
        data = {
            'id': device['device_id'] + device['entity_name']
        }
        select_instance = Selects(
            id=data['id'],
            device_serial_number=device['device_id'],
            data=device,
            type=device['device_type']
        )
        return select_instance, data['id']

    async def _handle_entity(self, entity: dict[str, Any]) -> (RedbackEntitys, str):
        """Handle entity data."""
        data = {
            'id': entity['device_id'] + entity['entity_name']
        }
        entity_instance = RedbackEntitys(
            entity_id=data['id'],
            device_id=entity['device_id'],
            type=entity['device_type'],
            data=entity,
        )
        return entity_instance, data['id']

    async def _handle_schedule(self, schedule: dict[str, Any]) -> (ScheduleInfo, str):
        """Handle schedule data."""
        data = {
            'id': schedule['schedule_id']
        }
        schedule_instance = ScheduleInfo(
            schedule_id=data['id'],
            data=schedule,
            device_serial_number = schedule['device_id'],
            start_time =  schedule['start_time_utc']
        )
        return schedule_instance, data['id']

    async def _handle_schedule_datetime(self, entity: dict[str, Any]) -> (ScheduleDateTime, str):
        """Handle schedule data."""
        data = {
            'id': entity['device_id'] + entity['entity_name']
        }
        schedule_instance = ScheduleDateTime(
            id=data['id'],
            device_serial_number = entity['device_id'],
            data=entity,
            type=entity['device_type']
        )
        return schedule_instance, data['id']
    
    async def _handle_inverter_calendar(self, entity: dict[str, Any]) -> dict[str, Any]:
        """Handle schedule data."""
        if entity["inverter_mode"] == "Auto":
            mode = 'Auto'
        elif entity["inverter_mode"] == 'ChargeBattery':
            mode = 'Charge Battery'
        elif entity["inverter_mode"] == 'DischargeBattery':
            mode = 'Discharge Battery'
        elif entity["inverter_mode"] == 'ExportPower':
            mode = 'Export Power'
        elif entity["inverter_mode"] == 'ImportPower':
            mode = 'Import Power'
        elif entity["inverter_mode"] == "BuyPower":
            mode = 'Buy Power'
        elif entity["inverter_mode"] == "SellPower":
            mode = 'Sell Power'
        elif entity["inverter_mode"] == "ForceChargeBattery":
            mode = 'Force Charge Battery'
        elif entity["inverter_mode"] == "ForceDischargeBattery":
            mode = 'Force Discharge Battery'
        elif entity["inverter_mode"] == "Conserve":
            mode = 'Conserve Battery'
        else:
            mode = entity["inverter_mode"]
        description_text = (
            "Inverter Serial Number: " + entity['serial_number']
            + " during this time the inverter will be in " + mode + " mode with a Power Level set at:"
            + str(entity["power_w"]) + " Watts"
            )
        
        data = {
            'schedule_selector' : entity['schedule_selector'],
            'uuid' : entity['schedule_id'],
            'start': entity['start_time_utc'],
            'end': entity['end_time'],
            'summary': entity['serial_number'] + ' ' + mode,
            'description': description_text,
            'device_id' : entity['device_id'],
            'device_type' : "inv",
            'power_level' : entity["power_w"],
            'power_mode' : mode
        }
        return data

    async def _handle_envelope_calendar(self, entity: dict[str, Any]) -> dict[str, Any]:
        """Handle schedule data."""

        description_text = (
            "Site: " + entity['data']['SiteId'] 
            + " Scheduled Operation Envelope."
            + " the site has the following Envelope defined during this time period: Max Import Power: "
            + str(entity['data']["MaxImportPowerW"])
            + "Watts, Max Export Power: " + str(entity['data']["MaxExportPowerW"])
            + "Watts, Max Discharge Power: " + str(entity['data']["MaxDischargePowerW"])
            + "Watts, Max Charge Power: " + str(entity['data']["MaxChargePowerW"])
            + ", Max Generation Power: " + str(entity['data']["MaxGenerationPowerVA"]) + "VA"
            )
        device_id = (entity['data']['SiteId'][-4:] + 'env').lower()
        data = {
            'schedule_selector' : entity['data']['schedule_selector'],
            'uuid' : entity['openv_id'],
            'start': entity['data']['StartAtUtc'],
            'end': entity['data']['EndAtUtc'],
            'summary': entity['data']['SiteId'] + ' Envelope Scheduled',
            'description': description_text,
            'device_id' : device_id,
            'device_type' : "env",
            "max_import_power" : entity['data']["MaxImportPowerW"],
            "max_export_power": entity['data']["MaxExportPowerW"],
            "max_discharge_power": entity['data']["MaxDischargePowerW"],
            "max_charge_power": entity['data']["MaxChargePowerW"],
            "max_generation_power": entity['data']["MaxGenerationPowerVA"],
        }
        return data

    async def _api_post(self, url: str, headers: dict[str, Any], data ) -> dict[str, Any]:
        """Make POST API call."""
        async with self._session1.post(url, headers=headers, data=data, timeout=self.timeout) as resp:
            return await self._api_response(resp)

    async def _api_post_json(self, url: str, headers: dict[str, Any], data ) -> dict[str, Any]:
        """Make POST API call."""
        async with self._session1.post(url, headers=headers, json=data, timeout=self.timeout) as resp:
            return await self._api_response(resp)

    async def _api_get(self, url: str, headers: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
        """Make GET API call."""
        async with self._session1.get(url, headers=headers, data=data, timeout=self.timeout) as resp:
            return await self._api_response(resp)

    async def _api_delete(self, url: str, headers: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
        """Make GET API call."""
        async with self._session1.delete(url, headers=headers, data=data, timeout=self.timeout) as resp:
            return await self._api_response(resp)

    @staticmethod
    async def _api_response(resp: ClientResponse):
        """Return response from API call."""
        if resp.status != 200:
            error = await resp.text()
            raise RedbackTechClientError(f'RedbackTech API Error Encountered. Status: {resp.status}; Error: {error}')
        try:
            response: dict[str, Any] = await resp.json()
        except Exception as error:
            raise RedbackTechClientError(f'Could not return json {error}') from error
        if 'error' in response:
            code = response['error']
            if code in AUTH_ERROR_CODES:
                raise AuthError(f'Redback API Error: {code}')
            else:
                raise RedbackTechClientError(f'RedbackTech API Error: {code}')
        return response

    async def _check_device_info_refresh(self) -> None:
        """Check to see if device info is about to expire.
        If there is no device info, a new device info is obtained. In addition,
        if the current device info is about to expire within 30 minutes
        or has already expired, a new device info is obtained.
        """
        current_dt = datetime.now()
        if self._device_info_refresh_time is None:
            return True
        elif (self._device_info_refresh_time-current_dt).total_seconds() < 10:
            return True
        else:
            return False

    async def _check_token(self) -> None:
        """Check to see if there is a valid token or if token is about to expire.
        If there is no token, a new token is obtained. In addition,
        if the current token is about to expire within 60 minutes
        or has already expired, a new token is obtained.
        """
        current_dt = datetime.now()
        if (self.token or self.token_expiration) is None:
            await self._api_login()
        elif (self.token_expiration-current_dt).total_seconds() < 300:
            await self._api_login()
        else:
            return None

    async def _get_portal_token(self, response, type):
        soup = BeautifulSoup(response , features="html.parser")
        if type == 1:
            form = soup.find("form", class_="login-form")
        else:
            form = soup.find('form', id='GlobalAntiForgeryToken')
        hidden_input = form.find("input", type="hidden")
        self._GAFToken = hidden_input.attrs['value']
        return

    async def _portal_post(self, url: str, headers: dict[str, Any], data ) -> dict[str, Any]:
        """Make POST Portal call."""
        async with self._session2.post(url, headers=headers, data=data, timeout=self.timeout) as resp:
            return await self._portal_response(resp)

    async def _portal_get(self, url: str, headers: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
        """Make GET Portal call."""
        async with self._session2.get(url, headers=headers, data=data, timeout=self.timeout) as resp:
            return await self._portal_response(resp)

    async def _portal_delete(self, url: str, headers: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
        """Make GET Portal call."""
        async with self._session2.delete(url, headers=headers, data=data, timeout=self.timeout) as resp:
            return await self._portal_response(resp)

    @staticmethod
    async def _portal_response(resp: ClientResponse):
        """Return response from Portal call."""
        LOGGER.debug('Portal Response: %s', resp)
        if resp.status != 200:
            error = await resp.text()
            raise RedbackTechClientError(f'RedbackTech API Error Encountered. Status: {resp.status}; Error: {error}')
        try:
            response: dict[str, Any] = await resp.text()
        except Exception as error:
            raise RedbackTechClientError(f'Could not return text {error}') from error
        return response

    async def _create_device_info_inverter(self, data) -> None:
        id_temp = data['Data']['Nodes'][0]['StaticData']['Id']
        id_temp = id_temp[-4:] + 'inv'
        id_temp = id_temp.lower()
        data_dict = {
            'identifiers': id_temp,
            'name': data['Data']['Nodes'][0]['StaticData']['ModelName'] + ' - inverter',
            'model': data['Data']['Nodes'][0]['StaticData']['ModelName'],
            'sw_version': data['Data']['Nodes'][0]['StaticData']['SoftwareVersion'],
            'hw_version': data['Data']['Nodes'][0]['StaticData']['FirmwareVersion'],
            'serial_number': data['Data']['Nodes'][0]['StaticData']['Id'],
        }
        self._redback_device_info.append(data_dict)
        return

    async def _create_device_info_op_env(self) -> None:
        for site in self._redback_site_ids:
            id_temp = site[-4:] + 'env'
            data_dict = {
                'identifiers': id_temp,
                'name': site + ' - Operating Envelope',
                'model': 'Redback Site Operating Envelope',
                'sw_version': 'API 2.0',
                'hw_version': '',
                'serial_number': site,
            }
            self._redback_device_info.append(data_dict)
        return

    async def _create_device_info_battery(self, data) -> None:
        id_temp = data['Data']['Nodes'][0]['StaticData']['Id']
        id_temp = id_temp[-4:] + 'bat'
        id_temp = id_temp.lower()
        data_dict = {
            'identifiers': id_temp,
            'name': data['Data']['Nodes'][0]['StaticData']['ModelName'] + ' - battery',
            'model': data['Data']['Nodes'][0]['StaticData']['ModelName'],
            'sw_version': data['Data']['Nodes'][0]['StaticData']['SoftwareVersion'],
            'hw_version': data['Data']['Nodes'][0]['StaticData']['FirmwareVersion'],
            'serial_number': data['Data']['Nodes'][0]['StaticData']['Id'],
        }
        self._redback_device_info.append(data_dict)
        return

    async def _create_op_env_datetime_entities(self, device_id, site) -> None:
        if self._redback_op_env_create_settings.get(device_id) is None:
            self._redback_op_env_create_settings.update([(device_id,{'EventId': '','MaxImportPowerW': 10000,'MaxExportPowerW': 10000,'MaxDischargePowerW': 10000,'MaxChargePowerW': 10000,'MaxGenerationPowerVA': 10000, 'StartAtUtc': datetime.now(timezone.utc), 'EndAtUtc': datetime.now(timezone.utc) + timedelta(hours=1), 'SiteId': site})])
        data_dict = {'value': self._redback_op_env_create_settings[device_id]['StartAtUtc'], 'entity_name': 'op_env_create_start_time', 'device_id': device_id, 'device_type': 'OperatingEnvelope', 'type_set': 'datetime.datetime' }
        self._redback_schedule_datetime.append(data_dict)
        data_dict = {'value': self._redback_op_env_create_settings[device_id]['EndAtUtc'], 'entity_name': 'op_env_create_end_time', 'device_id': device_id, 'device_type': 'OperatingEnvelope', 'type_set': 'datetime.datetime' }
        self._redback_schedule_datetime.append(data_dict)
        return

    async def _create_datetime_entities(self, data) -> None:
        id_temp = data['Data']['Nodes'][0]['StaticData']['Id']
        id_temp = id_temp[-4:] + 'inv'
        id_temp = id_temp.lower()

        if self._inverter_control_settings.get(id_temp) is None:    
            self._inverter_control_settings.update([(id_temp,{'power_setting_watts': 0,'power_setting_duration': 0,'power_setting_mode':'ChargeBattery', 'start_time': datetime.now(timezone.utc)})])
        data_dict = {'value': self._inverter_control_settings[id_temp]['start_time'], 'entity_name': 'schedule_create_start_time', 'device_id': id_temp, 'device_type': 'inverter', 'type_set': 'datetime.datetime' }
        self._redback_schedule_datetime.append(data_dict)
        return

    async def _create_op_env_number_entities(self, device_id, site) -> None:
        if self._redback_op_env_create_settings.get(device_id) is None:
            self._redback_op_env_create_settings.update([(device_id,{'EventId': '','MaxImportPowerW': 10000,'MaxExportPowerW': 10000,'MaxDischargePowerW': 10000,'MaxChargePowerW': 10000,'MaxGenerationPowerVA': 10000, 'StartAtUtc': datetime.now(timezone.utc), 'EndAtUtc': datetime.now(timezone.utc) + timedelta(hours=1), 'SiteId': site})])
        data_dict = {'value': self._redback_op_env_create_settings[device_id]['MaxImportPowerW'], 'entity_name': 'op_env_create_max_import', 'device_id': device_id, 'device_type': 'OperatingEnvelope', 'type_set': 'number.string' }
        self._redback_numbers.append(data_dict)
        data_dict = {'value': self._redback_op_env_create_settings[device_id]['MaxExportPowerW'], 'entity_name': 'op_env_create_max_export', 'device_id': device_id, 'device_type': 'OperatingEnvelope', 'type_set': 'number.string' }
        self._redback_numbers.append(data_dict)
        data_dict = {'value': self._redback_op_env_create_settings[device_id]['MaxDischargePowerW'], 'entity_name': 'op_env_create_max_discharge', 'device_id': device_id, 'device_type': 'OperatingEnvelope', 'type_set': 'number.string' }
        self._redback_numbers.append(data_dict)
        data_dict = {'value': self._redback_op_env_create_settings[device_id]['MaxChargePowerW'], 'entity_name': 'op_env_create_max_charge', 'device_id': device_id, 'device_type': 'OperatingEnvelope', 'type_set': 'number.string' }
        self._redback_numbers.append(data_dict)
        data_dict = {'value': self._redback_op_env_create_settings[device_id]['MaxGenerationPowerVA'], 'entity_name': 'op_env_create_max_generation', 'device_id': device_id, 'device_type': 'OperatingEnvelope', 'type_set': 'number.string' }
        self._redback_numbers.append(data_dict)
        return

    async def _create_op_env_text_entities(self, device_id, site) -> None:
        if self._redback_op_env_create_settings.get(device_id) is None:    
            self._redback_op_env_create_settings.update([(device_id,{'EventId': '','MaxImportPowerW': 10000,'MaxExportPowerW': 10000,'MaxDischargePowerW': 10000,'MaxChargePowerW': 10000,'MaxGenerationPowerVA': 10000, 'StartAtUtc': datetime.now(timezone.utc), 'EndAtUtc': datetime.now(timezone.utc) + timedelta(hours=1), 'SiteId': site})])
        data_dict = {'value': self._redback_op_env_create_settings[device_id]['EventId'], 'entity_name': 'op_env_create_event_id', 'device_id': device_id, 'device_type': 'OperatingEnvelope', 'type_set': 'text.string' }
        self._redback_text.append(data_dict)
        return
        
    async def _create_number_entities(self, data) -> None:
        id_temp = data['Data']['Nodes'][0]['StaticData']['Id']
        id_temp = id_temp[-4:] + 'inv'
        id_temp = id_temp.lower()

        if self._inverter_control_settings.get(id_temp) is None:
            self._inverter_control_settings.update([(id_temp,{'power_setting_watts': 0,'power_setting_duration': 0,'power_setting_mode':'ChargeBattery', 'start_time': datetime.now(timezone.utc)})])
        data_dict = {'value': self._inverter_control_settings[id_temp]['power_setting_duration'], 'entity_name': 'power_setting_duration', 'device_id': id_temp, 'device_type': 'inverter', 'type_set': 'number.string' }
        self._redback_numbers.append(data_dict)
        data_dict = {'value': self._inverter_control_settings[id_temp]['power_setting_watts'], 'entity_name': 'power_setting_watts', 'device_id': id_temp, 'device_type': 'inverter', 'type_set': 'number.string' }
        self._redback_numbers.append(data_dict)
        return

    async def _create_select_entities(self, data, data2) -> None:
        id_temp = data['Data']['Nodes'][0]['StaticData']['Id']
        id_temp = id_temp[-4:] + 'inv'
        id_temp = id_temp.lower()
        if self._inverter_control_settings.get(id_temp) is None:
            self._inverter_control_settings.update([(id_temp,{'power_setting_watts': 0,'power_setting_duration': 0,'power_setting_mode':'ChargeBattery'})])
        data_dict = {'value': self._inverter_control_settings[id_temp]['power_setting_mode'], 'entity_name': 'power_setting_mode', 'device_id': id_temp, 'device_type': 'inverter', 'type_set': 'select.string', 'options': INVERTER_MODES }
        self._redback_selects.append(data_dict)
        if self._redback_schedule_selected.get(id_temp) is None:
            self._redback_schedule_selected.update([(id_temp,{'schedule_selector': None})])
        if self._redback_schedules is not None:
            schedule_options=[]
            for schedule in self._redback_schedules:
                if schedule['device_id'] == id_temp:
                    schedule_options.append(schedule['schedule_selector'])
            data_dict = {'value': self._redback_schedule_selected[id_temp]['schedule_selector'], 'entity_name': 'schedule_id_selected', 'device_id': id_temp, 'device_type': 'inverter', 'type_set': 'select.string', 'options': schedule_options}
        else:
            data_dict = {'value': None, 'entity_name': 'schedule_id_selected', 'device_id': id_temp, 'device_type': 'inverter', 'type_set': 'select.string', 'options': None}
        self._redback_selects.append(data_dict)
        return

    async def _create_op_env_select_entities(self, site, device_id) -> None:
        if self._redback_op_env_selected.get(device_id) is None:
            self._redback_op_env_selected.update([(device_id,{'schedule_selector': None})])
        if self._redback_open_env_data is not None:
            schedule_options=[]
            for schedule in self._redback_open_env_data:
                if schedule['data']['SiteId'] == site:
                    schedule_options.append(schedule['data']['schedule_selector'])
            data_dict = {'value': self._redback_op_env_selected[device_id]['schedule_selector'], 'entity_name': 'op_env_id_selected', 'device_id': device_id, 'device_type': 'inverter', 'type_set': 'select.string', 'options': schedule_options}
        else:
            data_dict = {'value': None, 'entity_name': 'op_env_id_selected', 'device_id': device_id, 'device_type': 'inverter', 'type_set': 'select.string', 'options': None}
        self._redback_selects.append(data_dict)
        return

    async def _create_op_env_status_entities(self, site, device_id, schedule_count) -> None:
        data_dict = {'value': self._redback_op_env_data[site], 'entity_name': 'op_env_has_env', 'device_id': device_id, 'device_type': 'OperatingEnvelope', 'type_set': 'select.string'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': schedule_count, 'entity_name': 'op_env_count', 'device_id': device_id, 'device_type': 'OperatingEnvelope', 'type_set': 'select.string'}
        self._redback_entities.append(data_dict)
        return

    async def _convert_responses_to_schedule_entities(self, data, data2) -> None:
        id_temp = data2['Data']['Nodes'][0]['StaticData']['Id']
        id_temp = id_temp[-4:] + 'inv'
        id_temp = id_temp.lower()
        temp_timenow = datetime.now(timezone.utc)
        temp_active_event = False
        if len(data['Data']['Schedules']) != 0:
            for schedule in data['Data']['Schedules']:
                days =0
                if schedule['Duration'].find('.')> -1:
                    days = int(schedule['Duration'].split('.')[0]) *24*60
                    schedule['Duration'] = schedule['Duration'].split('.')[1]
                schedule['Duration'] = int(schedule['Duration'].split(':')[0])*60 + int(schedule['Duration'].split(':')[1]) + days
                end_time = (datetime.fromisoformat((schedule['StartTimeUtc']).replace('Z','+00:00')) + timedelta(minutes=schedule['Duration']))
                data_dict = {
                    'schedule_selector': str((datetime.fromisoformat((schedule['StartTimeUtc']).replace('Z','+00:00'))).astimezone())[:16] +'-' + schedule['DesiredMode']['InverterMode'],
                    'schedule_id': schedule['ScheduleId'],
                    'serial_number': schedule['SerialNumber'],
                    'siteid': schedule['SiteId'],
                    'start_time_utc': datetime.fromisoformat((schedule['StartTimeUtc']).replace('Z','+00:00')),
                    'end_time': end_time,
                    'duration': schedule['Duration'],
                    'inverter_mode': schedule['DesiredMode']['InverterMode'],
                    'power_w': schedule['DesiredMode']['ArgumentInWatts'],   
                    'device_id': id_temp,
                    'device_type': 'inverter',         
                }
                self._redback_schedules.append(data_dict)
                if temp_timenow >= datetime.fromisoformat((schedule['StartTimeUtc']).replace('Z','+00:00')) and temp_timenow <= end_time:
                    temp_active_event = True
                    active_event = {'value': datetime.fromisoformat((schedule['StartTimeUtc']).replace('Z','+00:00')), 'entity_name': 'active_event_start_time', 'device_id': id_temp, 'device_type': 'inverter', 'type_set': 'datetime.datetime' }
                    self._redback_entities.append(active_event)
                    active_event = {'value': end_time, 'entity_name': 'active_event_end_time', 'device_id': id_temp, 'device_type': 'inverter', 'type_set': 'datetime.datetime' }
                    self._redback_entities.append(active_event)
                    active_event = {'value': schedule['Duration'], 'entity_name': 'active_event_duration', 'device_id': id_temp, 'device_type': 'inverter', 'type_set': 'number.string' }
                    self._redback_entities.append(active_event)
                    active_event = {'value': schedule['DesiredMode']['InverterMode'], 'entity_name': 'active_event_inverter_mode', 'device_id': id_temp, 'device_type': 'inverter', 'type_set': 'select.string', 'options': INVERTER_MODES }
                    self._redback_entities.append(active_event)
                    active_event = {'value': schedule['DesiredMode']['ArgumentInWatts'], 'entity_name': 'active_event_power_w', 'device_id': id_temp, 'device_type': 'inverter', 'type_set': 'number.string' }
                    self._redback_entities.append(active_event)
                    active_event = {'value': schedule['ScheduleId'], 'entity_name': 'active_event_schedule_id', 'device_id': id_temp, 'device_type': 'inverter', 'type_set': 'number.string' }
                    self._redback_entities.append(active_event)
                    active_event = {'value': True, 'entity_name': 'active_event', 'device_id': id_temp, 'device_type': 'inverter', 'type_set': 'number.string' }
                    self._redback_entities.append(active_event)
        if temp_active_event is False:    
            active_event = {'value': None, 'entity_name': 'active_event_start_time', 'device_id': id_temp, 'device_type': 'inverter', 'type_set': 'datetime.datetime' }
            self._redback_entities.append(active_event)
            active_event = {'value': None, 'entity_name': 'active_event_end_time', 'device_id': id_temp, 'device_type': 'inverter', 'type_set': 'datetime.datetime' }
            self._redback_entities.append(active_event)
            active_event = {'value': 0, 'entity_name': 'active_event_duration', 'device_id': id_temp, 'device_type': 'inverter', 'type_set': 'number.string' }
            self._redback_entities.append(active_event)
            active_event = {'value': None, 'entity_name': 'active_event_inverter_mode', 'device_id': id_temp, 'device_type': 'inverter', 'type_set': 'select.string', 'options': INVERTER_MODES }
            self._redback_entities.append(active_event)
            active_event = {'value': 0, 'entity_name': 'active_event_power_w', 'device_id': id_temp, 'device_type': 'inverter', 'type_set': 'number.string' }
            self._redback_entities.append(active_event)
            active_event = {'value': None, 'entity_name': 'active_event_schedule_id', 'device_id': id_temp, 'device_type': 'inverter', 'type_set': 'number.string' }
            self._redback_entities.append(active_event)
            active_event = {'value': False, 'entity_name': 'active_event', 'device_id': id_temp, 'device_type': 'inverter', 'type_set': 'number.string' }
            self._redback_entities.append(active_event)
        return

    async def _convert_responses_to_inverter_entities(self, data, data2) -> None:
        """Convert responses to entities."""
        pvId =1
        id_temp = data['Data']['Nodes'][0]['StaticData']['Id']
        id_temp = id_temp[-4:] + 'inv'
        id_temp = id_temp.lower()
        data_dict = {'value': data['Data']['Nodes'][0]['StaticData']['ModelName'], 'entity_name': 'model_name', 'device_id': id_temp, 'device_type': 'inverter', 'type_set': 'sensor.string' }
        self._redback_entities.append(data_dict)
        data_dict = {'value': data['Data']['Nodes'][0]['StaticData']['Id'], 'entity_name': 'serial_number', 'device_id': id_temp, 'device_type': 'inverter', 'type_set': 'sensor.string' }
        self._redback_entities.append(data_dict)
        data_dict = {'value': data['Data']['StaticData']['Location']['Latitude'], 'entity_name': 'latitude', 'device_id': id_temp, 'device_type': 'inverter', 'type_set': 'sensor.string' }
        self._redback_entities.append(data_dict)
        data_dict = { 'value': data['Data']['StaticData']['Location']['Longitude'], 'entity_name': 'longitude', 'device_id': id_temp, 'device_type': 'inverter', 'type_set': 'sensor.string' }
        self._redback_entities.append(data_dict)
        data_dict = {'value': data['Data']['StaticData']['RemoteAccessConnection']['Type'],'entity_name': 'network_connection', 'device_id': id_temp, 'device_type': 'inverter'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': data['Data']['StaticData']['ApprovedCapacityW'],'entity_name': 'approved_capacity_w', 'device_id': id_temp, 'device_type': 'inverter'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': data['Data']['StaticData']['SiteDetails']['GenerationHardLimitVA'],'entity_name': 'generation_hard_limit_va', 'device_id': id_temp, 'device_type': 'inverter'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': data['Data']['StaticData']['SiteDetails']['GenerationSoftLimitVA'],'entity_name': 'generation_soft_limit_va', 'device_id': id_temp, 'device_type': 'inverter'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': data['Data']['StaticData']['SiteDetails']['ExportHardLimitkW'],'entity_name': 'export_hard_limit_kw', 'device_id': id_temp, 'device_type': 'inverter'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': data['Data']['StaticData']['SiteDetails']['ExportSoftLimitkW'],'entity_name': 'export_soft_limit_kw', 'device_id': id_temp, 'device_type': 'inverter'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': data['Data']['StaticData']['SiteDetails']['SiteExportLimitkW'],'entity_name': 'site_export_limit_kw', 'device_id': id_temp, 'device_type': 'inverter'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': data['Data']['StaticData']['SiteDetails']['PanelModel'],'entity_name': 'pv_panel_model', 'device_id': id_temp, 'device_type': 'inverter'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': data['Data']['StaticData']['SiteDetails']['PanelSizekW'],'entity_name': 'pv_panel_size_kw', 'device_id': id_temp, 'device_type': 'inverter'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': data['Data']['StaticData']['SiteDetails']['SystemType'],'entity_name': 'system_type', 'device_id': id_temp, 'device_type': 'inverter'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': data['Data']['StaticData']['SiteDetails']['InverterMaxExportPowerkW'],'entity_name': 'inverter_max_export_power_kw', 'device_id': id_temp, 'device_type': 'inverter'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': data['Data']['StaticData']['SiteDetails']['InverterMaxImportPowerkW'],'entity_name': 'inverter_max_import_power_kw', 'device_id': id_temp, 'device_type': 'inverter'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': data['Data']['StaticData']['CommissioningDate'],'entity_name': 'commissioning_date', 'device_id': id_temp, 'device_type': 'inverter'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': data['Data']['StaticData']['NMI'],'entity_name': 'nmi', 'device_id': id_temp, 'device_type': 'inverter'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': data['Data']['StaticData']['Id'],'entity_name': 'site_id', 'device_id': id_temp, 'device_type': 'inverter'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': data['Data']['StaticData']['Type'],'entity_name': 'inverter_site_type', 'device_id': id_temp, 'device_type': 'inverter'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': data['Data']['Nodes'][0]['StaticData']['BatteryCount'],'entity_name': 'battery_count', 'device_id': id_temp, 'device_type': 'inverter'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': data['Data']['Nodes'][0]['StaticData']['SoftwareVersion'],'entity_name': 'software_version', 'device_id': id_temp, 'device_type': 'inverter'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': data['Data']['Nodes'][0]['StaticData']['FirmwareVersion'],'entity_name': 'firmware_version', 'device_id': id_temp, 'device_type': 'inverter'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': datetime.fromisoformat((data2['Data']['TimestampUtc']).replace('Z','+00:00')),'entity_name': 'timestamp_utc', 'device_id': id_temp, 'device_type': 'inverter'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': data2['Data']['FrequencyInstantaneousHz'],'entity_name': 'frequency_instantaneous', 'device_id': id_temp, 'device_type': 'inverter'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': data2['Data']['PvPowerInstantaneouskW'],'entity_name': 'pv_power_instantaneous_kw', 'device_id': id_temp, 'device_type': 'inverter'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': data2['Data']['InverterTemperatureC'],'entity_name': 'inverter_temperature_c', 'device_id': id_temp, 'device_type': 'inverter'}
        self._redback_entities.append(data_dict)
        if data2['Data']['PvAllTimeEnergykWh'] is not None:
            data_dict = {'value': (data2['Data']['PvAllTimeEnergykWh'])/1000,'entity_name': 'pv_all_time_energy_mwh', 'device_id': id_temp, 'device_type': 'inverter'}
        else:
            data_dict = {'value': data2['Data']['PvAllTimeEnergykWh'],'entity_name': 'pv_all_time_energy_mwh', 'device_id': id_temp, 'device_type': 'inverter'}
        self._redback_entities.append(data_dict)
        if data2['Data']['ExportAllTimeEnergykWh'] is not None:
            data_dict = {'value': (data2['Data']['ExportAllTimeEnergykWh'])/1000,'entity_name': 'export_all_time_energy_mwh', 'device_id': id_temp, 'device_type': 'inverter'}
        else:
            data_dict = {'value': data2['Data']['ExportAllTimeEnergykWh'],'entity_name': 'export_all_time_energy_mwh', 'device_id': id_temp, 'device_type': 'inverter'}
        self._redback_entities.append(data_dict)
        if data2['Data']['ImportAllTimeEnergykWh'] is not None:
            data_dict = {'value': (data2['Data']['ImportAllTimeEnergykWh'])/1000,'entity_name': 'import_all_time_energy_mwh', 'device_id': id_temp, 'device_type': 'inverter'}
        else:
            data_dict = {'value': data2['Data']['ImportAllTimeEnergykWh'],'entity_name': 'import_all_time_energy_mwh', 'device_id': id_temp, 'device_type': 'inverter'}  
        self._redback_entities.append(data_dict)
        if data2['Data']['LoadAllTimeEnergykWh'] is not None:
            data_dict = {'value': (data2['Data']['LoadAllTimeEnergykWh'])/1000,'entity_name': 'load_all_time_energy_mwh', 'device_id': id_temp, 'device_type': 'inverter'}   
        else:
            data_dict = {'value': data2['Data']['LoadAllTimeEnergykWh'],'entity_name': 'load_all_time_energy_mwh', 'device_id': id_temp, 'device_type': 'inverter'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': data2['Data']['Status'],'entity_name': 'status', 'device_id': id_temp, 'device_type': 'inverter'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': data2['Data']['Inverters'][0]['PowerMode']['InverterMode'],'entity_name': 'power_mode_inverter_mode', 'device_id': id_temp, 'device_type': 'inverter'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': data2['Data']['Inverters'][0]['PowerMode']['PowerW'],'entity_name': 'power_mode_power_w', 'device_id': id_temp, 'device_type': 'inverter'}
        self._redback_entities.append(data_dict)
        for pv in data2['Data']['PVs']:
            entity_name_temp = f'mppt_{pvId}_current_a'
            data_dict = {'value': pv['CurrentA'],'entity_name': entity_name_temp, 'device_id': id_temp, 'device_type': 'inverter'}
            self._redback_entities.append(data_dict)
            entity_name_temp = f'mppt_{pvId}_voltage_v'
            data_dict = {'value': pv['VoltageV'],'entity_name': entity_name_temp, 'device_id': id_temp, 'device_type': 'inverter'}
            self._redback_entities.append(data_dict)
            entity_name_temp = f'mppt_{pvId}_power_kw'
            data_dict = {'value': pv['PowerkW'],'entity_name': entity_name_temp, 'device_id': id_temp, 'device_type': 'inverter'}
            self._redback_entities.append(data_dict)
            if data['Data']['Nodes'][0]['StaticData']['Id'] in self._redback_mppt_data:
                if ("mppt_"+str(pvId)) in self._redback_mppt_data[data['Data']['Nodes'][0]['StaticData']['Id']]:
                    if "pv_size" in self._redback_mppt_data[data['Data']['Nodes'][0]['StaticData']['Id']]["mppt_"+str(pvId)]:
                        entity_name_temp = f'mppt_{pvId}_size_kw'
                        data_dict = {'value': round(float(self._redback_mppt_data[data['Data']['Nodes'][0]['StaticData']['Id']]["mppt_"+str(pvId)]["pv_size"]),3) ,'entity_name': entity_name_temp, 'device_id': id_temp, 'device_type': 'inverter'}
                        self._redback_entities.append(data_dict)
                        entity_name_temp = f'mppt_{pvId}_generation_instant'
                        temp_data =round(( pv['PowerkW'] /float(self._redback_mppt_data[data['Data']['Nodes'][0]['StaticData']['Id']]["mppt_"+str(pvId)]["pv_size"])) * 100,2)
                        data_dict = {'value': temp_data ,'entity_name': entity_name_temp, 'device_id': id_temp, 'device_type': 'inverter'}
                        self._redback_entities.append(data_dict)
                    if "pv_number_panels" in self._redback_mppt_data[data['Data']['Nodes'][0]['StaticData']['Id']]["mppt_"+str(pvId)]:
                        entity_name_temp = f'mppt_{pvId}_number_panels'
                        data_dict = {'value': self._redback_mppt_data[data['Data']['Nodes'][0]['StaticData']['Id']]["mppt_"+str(pvId)]["pv_number_panels"] ,'entity_name': entity_name_temp, 'device_id': id_temp, 'device_type': 'inverter'}
                        self._redback_entities.append(data_dict)
                    if "pv_panel_direction" in self._redback_mppt_data[data['Data']['Nodes'][0]['StaticData']['Id']]["mppt_"+str(pvId)]:
                        entity_name_temp = f'mppt_{pvId}_panel_direction'
                        data_dict = {'value': self._redback_mppt_data[data['Data']['Nodes'][0]['StaticData']['Id']]["mppt_"+str(pvId)]["pv_panel_direction"] ,'entity_name': entity_name_temp, 'device_id': id_temp, 'device_type': 'inverter'}
                        self._redback_entities.append(data_dict)
                    
            pvId += 1
        phase_count = 0
        phase_voltage_sum = 0
        phase_Current_sum = 0
        phase_power_exported_sum = 0
        phase_power_imported_sum = 0
        phase_power_net_sum = 0
        for phase in data2['Data']['Phases']:  
            if phase['VoltageInstantaneousV'] is not None:
                phase_count += 1
                phase_voltage_sum += phase['VoltageInstantaneousV']
                phase_Current_sum += phase['CurrentInstantaneousA']
                phase_power_exported_sum += phase['ActiveExportedPowerInstantaneouskW']
                phase_power_imported_sum += phase['ActiveImportedPowerInstantaneouskW'] 
                phase_power_net_sum += phase['ActiveImportedPowerInstantaneouskW'] - phase['ActiveExportedPowerInstantaneouskW']
            phaseAlpha=phase['Id'].lower()
            entity_name_temp = f'inverter_phase_{phaseAlpha}_active_exported_power_instantaneous_kw'
            data_dict = {'value': phase['ActiveExportedPowerInstantaneouskW'],'entity_name': entity_name_temp, 'device_id': id_temp, 'device_type': 'inverter'}
            self._redback_entities.append(data_dict)
            entity_name_temp = f'inverter_phase_{phaseAlpha}_active_imported_power_instantaneous_kw'
            data_dict = {'value': phase['ActiveImportedPowerInstantaneouskW'],'entity_name': entity_name_temp, 'device_id': id_temp, 'device_type': 'inverter'}
            self._redback_entities.append(data_dict)
            entity_name_temp = f'inverter_phase_{phaseAlpha}_active_net_power_instantaneous_kw'
            data_dict = {'value': phase['ActiveImportedPowerInstantaneouskW'] - phase['ActiveExportedPowerInstantaneouskW'],'entity_name': entity_name_temp, 'device_id': id_temp, 'device_type': 'inverter'}
            self._redback_entities.append(data_dict)
            entity_name_temp = f'inverter_phase_{phaseAlpha}_voltage_instantaneous_v'
            data_dict = {'value': phase['VoltageInstantaneousV'],'entity_name': entity_name_temp, 'device_id': id_temp, 'device_type': 'inverter'}
            self._redback_entities.append(data_dict)
            entity_name_temp = f'inverter_phase_{phaseAlpha}_current_instantaneous_a'
            data_dict = {'value': phase['CurrentInstantaneousA'],'entity_name': entity_name_temp, 'device_id': id_temp, 'device_type': 'inverter'}
            self._redback_entities.append(data_dict)
            entity_name_temp = f'inverter_phase_{phaseAlpha}_power_factor_instantaneous_minus_1to1'
            data_dict = {'value': phase['PowerFactorInstantaneousMinus1to1'],'entity_name': entity_name_temp, 'device_id': id_temp, 'device_type': 'inverter'}
            self._redback_entities.append(data_dict)
        self._redback_temp_voltage[(data['Data']['Nodes'][0]['StaticData']['Id'])] = round( phase_voltage_sum / phase_count * sqrt(phase_count), 1)
        data_dict = {'value': round( phase_voltage_sum / phase_count * sqrt(phase_count), 1), 'entity_name': 'inverter_phase_total_voltage_instantaneous_v', 'device_id': id_temp, 'device_type': 'inverter'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': phase_Current_sum, 'entity_name': 'inverter_phase_total_current_instantaneous_a', 'device_id': id_temp, 'device_type': 'inverter'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': phase_power_exported_sum, 'entity_name': 'inverter_phase_total_active_exported_power_instantaneous_kw', 'device_id': id_temp, 'device_type': 'inverter'} 
        self._redback_entities.append(data_dict)
        data_dict = {'value': phase_power_imported_sum, 'entity_name': 'inverter_phase_total_active_imported_power_instantaneous_kw', 'device_id': id_temp, 'device_type': 'inverter'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': round(phase_power_net_sum,3), 'entity_name': 'inverter_phase_total_active_net_power_instantaneous_kw', 'device_id': id_temp, 'device_type': 'inverter'}
        self._redback_entities.append(data_dict)
        pv_percent = (data2['Data']['PvPowerInstantaneouskW'] / data['Data']['StaticData']['SiteDetails']['PanelSizekW']) * 100
        data_dict = {'value': round(pv_percent,0), 'entity_name': 'pv_generation_instantaneous_percent_capacity', 'device_id': id_temp, 'device_type': 'inverter'}
        self._redback_entities.append(data_dict)
        self._redback_site_load[(data['Data']['Nodes'][0]['StaticData']['Id'])] = phase_power_net_sum + data2['Data']['PvPowerInstantaneouskW']
        return
        
    async def _convert_responses_to_battery_entities(self, data, data2, soc_data) -> None:
        batteryName = 'Unknown'
        batteryId = 1
        cabinetId = 1
        id_temp = data['Data']['Nodes'][0]['StaticData']['Id']
        id_temp = id_temp[-4:] + 'bat'
        id_temp = id_temp.lower()
        data_dict = {'value': (soc_data['Data']['MinSoC0to1'])*100,'entity_name': 'min_soc_0_to_1', 'device_id': id_temp, 'device_type': 'battery'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': (soc_data['Data']['MinOffgridSoC0to1'])*100,'entity_name': 'min_Offgrid_soc_0_to_1', 'device_id': id_temp, 'device_type': 'battery'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': data['Data']['StaticData']['Location']['Latitude'],'entity_name': 'latitude', 'device_id': id_temp, 'device_type': 'battery'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': data['Data']['StaticData']['Location']['Longitude'],'entity_name': 'longitude', 'device_id': id_temp, 'device_type': 'battery'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': data['Data']['StaticData']['SiteDetails']['BatteryMaxChargePowerkW'],'entity_name': 'battery_max_charge_power_kw', 'device_id': id_temp, 'device_type': 'battery'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': data['Data']['StaticData']['SiteDetails']['BatteryMaxDischargePowerkW'],'entity_name': 'battery_max_discharge_power_kw', 'device_id': id_temp, 'device_type': 'battery'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': data['Data']['StaticData']['SiteDetails']['BatteryCapacitykWh'],'entity_name': 'battery_capacity_kwh', 'device_id': id_temp, 'device_type': 'battery'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': data['Data']['StaticData']['SiteDetails']['UsableBatteryCapacitykWh'],'entity_name': 'battery_usable_capacity_kwh', 'device_id': id_temp, 'device_type': 'battery'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': data['Data']['StaticData']['SiteDetails']['SystemType'],'entity_name': 'system_type', 'device_id': id_temp, 'device_type': 'battery'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': data['Data']['StaticData']['CommissioningDate'],'entity_name': 'commissioning_date', 'device_id': id_temp, 'device_type': 'battery'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': data['Data']['StaticData']['Id'],'entity_name': 'site_id', 'device_id': id_temp, 'device_type': 'battery'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': data['Data']['StaticData']['Type'],'entity_name': 'inverter_site_type', 'device_id': id_temp, 'device_type': 'battery'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': data['Data']['Nodes'][0]['StaticData']['ModelName'],'entity_name': 'model_name', 'device_id': id_temp, 'device_type': 'battery'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': data['Data']['Nodes'][0]['StaticData']['BatteryCount'],'entity_name': 'battery_count', 'device_id': id_temp, 'device_type': 'battery'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': data['Data']['Nodes'][0]['StaticData']['SoftwareVersion'],'entity_name': 'software_version', 'device_id': id_temp, 'device_type': 'battery'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': data['Data']['Nodes'][0]['StaticData']['FirmwareVersion'],'entity_name': 'firmware_version', 'device_id': id_temp, 'device_type': 'battery'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': data['Data']['Nodes'][0]['StaticData']['Id'],'entity_name': 'inverter_serial_number', 'device_id': id_temp, 'device_type': 'battery'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': datetime.fromisoformat((data2['Data']['TimestampUtc']).replace('Z','+00:00')),'entity_name': 'timestamp_utc', 'device_id': id_temp, 'device_type': 'inverter'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': (data2['Data']['BatterySoCInstantaneous0to1'])*100,'entity_name': 'battery_soc_instantaneous_0to1', 'device_id': id_temp, 'device_type': 'battery'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': data2['Data']['BatteryPowerNegativeIsChargingkW'],'entity_name': 'battery_power_negative_is_charging_kw', 'device_id': id_temp, 'device_type': 'battery'}
        self._redback_entities.append(data_dict)
        if data2['Data']['BatteryChargeAllTimeEnergykWh'] is not None:
            data_dict = {'value': (data2['Data']['BatteryChargeAllTimeEnergykWh'])/1000,'entity_name': 'battery_charge_all_time_energy_mwh', 'device_id': id_temp, 'device_type': 'battery'}
        else:
            data_dict = {'value': data2['Data']['BatteryChargeAllTimeEnergykWh'],'entity_name': 'battery_charge_all_time_energy_mwh', 'device_id': id_temp, 'device_type': 'battery'}
        self._redback_entities.append(data_dict)
        if data2['Data']['BatteryDischargeAllTimeEnergykWh'] is not None:
            data_dict = {'value': (data2['Data']['BatteryDischargeAllTimeEnergykWh'])/1000,'entity_name': 'battery_discharge_all_time_energy_mwh', 'device_id': id_temp, 'device_type': 'battery'}
        else:
            data_dict = {'value': data2['Data']['BatteryDischargeAllTimeEnergykWh'],'entity_name': 'battery_discharge_all_time_energy_mwh', 'device_id': id_temp, 'device_type': 'battery'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': data2['Data']['Status'],'entity_name': 'status', 'device_id': id_temp, 'device_type': 'battery'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': data2['Data']['Battery']['CurrentNegativeIsChargingA'],'entity_name': 'battery_current_negative_is_charging_a', 'device_id': id_temp, 'device_type': 'battery'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': data2['Data']['Battery']['VoltageV'],'entity_name': 'battery_voltage_v', 'device_id': id_temp, 'device_type': 'battery'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': data2['Data']['Battery']['VoltageType'],'entity_name': 'battery_voltage_type', 'device_id': id_temp, 'device_type': 'battery'}
        self._redback_entities.append(data_dict)
        data_dict = {'value': data2['Data']['Battery']['NumberOfModules'],'entity_name': 'battery_no_of_modules', 'device_id': id_temp, 'device_type': 'battery'}
        self._redback_entities.append(data_dict)
        data_dict = {'value':(data['Data']['StaticData']['SiteDetails']['BatteryCapacitykWh'] * data2['Data']['BatterySoCInstantaneous0to1'] ),'entity_name': 'battery_currently_stored_kwh', 'device_id': id_temp, 'device_type': 'battery'}
        self._redback_entities.append(data_dict)
        data_dict = {'value':  round(data['Data']['StaticData']['SiteDetails']['BatteryCapacitykWh'] * (data2['Data']['BatterySoCInstantaneous0to1']- soc_data['Data']['MinSoC0to1']),2),'entity_name': 'battery_currently_usable_kwh', 'device_id': id_temp, 'device_type': 'battery'}
        self._redback_entities.append(data_dict)
        battery_current_a = 0
        battery_power_kw = 0
        for battery in data['Data']['Nodes'][0]['StaticData']['BatteryModels']:
            if battery != 'Unknown':
                batteryName = battery
                data_dict = {'value': batteryName,'entity_name': f'battery_{batteryId}_model', 'device_id': id_temp, 'device_type': 'battery'}
                self._redback_entities.append(data_dict)
            else:
                data_dict = {'value': batteryName,'entity_name': f'battery_{batteryId}_model', 'device_id': id_temp, 'device_type': 'battery'}
                self._redback_entities.append(data_dict)
            battery_temp_value = data2['Data']['Battery']['Modules'][batteryId-1]['CurrentNegativeIsChargingA']
            battery_current_a += battery_temp_value
            battery_temp_name= f'battery_{batteryId}_current_negative_is_charging_a'
            data_dict = {'value': battery_temp_value,'entity_name': battery_temp_name, 'device_id': id_temp, 'device_type': 'battery'}
            self._redback_entities.append(data_dict)
            battery_temp_value = data2['Data']['Battery']['Modules'][batteryId-1]['VoltageV']
            battery_temp_name= f'battery_{batteryId}_voltage_v'
            data_dict = {'value': battery_temp_value,'entity_name': battery_temp_name, 'device_id': id_temp, 'device_type': 'battery'}
            self._redback_entities.append(data_dict)
            battery_temp_value = data2['Data']['Battery']['Modules'][batteryId-1]['PowerNegativeIsChargingkW']
            battery_power_kw += battery_temp_value
            battery_temp_name= f'battery_{batteryId}_power_negative_is_charging_kw'
            data_dict = {'value': battery_temp_value,'entity_name': battery_temp_name, 'device_id': id_temp, 'device_type': 'battery'}
            self._redback_entities.append(data_dict)
            battery_temp_value = (data2['Data']['Battery']['Modules'][batteryId-1]['SoC0To1'])*100
            battery_temp_name= f'battery_{batteryId}_soc_0to1'
            data_dict = {'value': battery_temp_value,'entity_name': battery_temp_name, 'device_id': id_temp, 'device_type': 'battery'}
            self._redback_entities.append(data_dict)
            batteryId += 1
        data_dict = {'value': round(data2['Data']['BatteryPowerNegativeIsChargingkW']*1000/self._redback_temp_voltage[(data['Data']['Nodes'][0]['StaticData']['Id'])],1),'entity_name': 'battery_current_negative_is_charging_a', 'device_id': id_temp, 'device_type': 'battery'}
        self._redback_entities.append(data_dict)
        for cabinet in data2['Data']['Battery']['Cabinets']:
            cabinet_temp_name = f'battery_cabinet_{cabinetId}_temperature_c'
            data_dict = {'value': cabinet['TemperatureC'],'entity_name': cabinet_temp_name, 'device_id': id_temp, 'device_type': 'battery'}
            self._redback_entities.append(data_dict)
            cabinet_temp_name = f'battery_cabinet_{cabinetId}_fan_state'
            data_dict = {'value': cabinet['FanState'],'entity_name': cabinet_temp_name, 'device_id': id_temp, 'device_type': 'battery'}
            self._redback_entities.append(data_dict)
            cabinetId += 1
        self._redback_site_load[(data['Data']['Nodes'][0]['StaticData']['Id'])] += data2['Data']['BatteryPowerNegativeIsChargingkW']
        return

    async def _add_additional_entities(self, site_load_data, data):
        id_temp = data['Data']['Nodes'][0]['StaticData']['Id']
        id_temp = id_temp[-4:] + 'inv'
        id_temp = id_temp.lower()
        value_temp= round(site_load_data,3)
        data_dict = {'value': value_temp,'entity_name': 'inverter_site_load_instantaneous_kw', 'device_id': id_temp, 'device_type': 'inverter'}
        self._redback_entities.append(data_dict)
        return

    async def _create_op_env_active_entities(self, data, device_id, site):
        if data is None:
            data_dict = {'value': self._redback_op_env_active[site], 'entity_name': 'op_env_active_now', 'device_id': device_id, 'device_type': 'OperatingEnvelope', 'type_set': 'sensor.string' }
            self._redback_entities.append(data_dict)
            data_dict = {'value': 'No Active Event','entity_name': 'op_env_active_event_id', 'device_id': device_id, 'device_type': 'OperatingEnvelope', 'type_set': 'sensor.string' }
            self._redback_entities.append(data_dict)
            data_dict = {'value': None,'entity_name': 'op_env_active_nmi', 'device_id': device_id, 'device_type': 'OperatingEnvelope', 'type_set': 'sensor.string' }
            self._redback_entities.append(data_dict)
            data_dict = {'value': None,'entity_name': 'op_env_active_site_id', 'device_id': device_id, 'device_type': 'OperatingEnvelope', 'type_set': 'sensor.string' }
            self._redback_entities.append(data_dict)
            data_dict = {'value': None,'entity_name': 'op_env_active_start_datetime', 'device_id': device_id, 'device_type': 'OperatingEnvelope', 'type_set': 'sensor.datetime' }
            self._redback_entities.append(data_dict)
            data_dict = {'value': None,'entity_name': 'op_env_active_end_datetime', 'device_id': device_id, 'device_type': 'OperatingEnvelope', 'type_set': 'sensor.datetime' }
            self._redback_entities.append(data_dict)
            data_dict = {'value': 0,'entity_name': 'op_env_active_max_import_power_w', 'device_id': device_id, 'device_type': 'OperatingEnvelope', 'type_set': 'sensor.integer' }
            self._redback_entities.append(data_dict)
            data_dict = {'value': 0,'entity_name': 'op_env_active_max_export_power_w', 'device_id': device_id, 'device_type': 'OperatingEnvelope', 'type_set': 'sensor.integer' }
            self._redback_entities.append(data_dict)
            data_dict = {'value': 0,'entity_name': 'op_env_active_max_discharge_power_w', 'device_id': device_id, 'device_type': 'OperatingEnvelope', 'type_set': 'sensor.integer' }
            self._redback_entities.append(data_dict)
            data_dict = {'value': 0,'entity_name': 'op_env_active_max_charge_power_w', 'device_id': device_id, 'device_type': 'OperatingEnvelope', 'type_set': 'sensor.integer' }
            self._redback_entities.append(data_dict)
            data_dict = {'value': 0,'entity_name': 'op_env_active_max_generation_power_va', 'device_id': device_id, 'device_type': 'OperatingEnvelope', 'type_set': 'sensor.integer' }
            self._redback_entities.append(data_dict)
            data_dict = {'value': None,'entity_name': 'op_env_active_is_network_level', 'device_id': device_id, 'device_type': 'OperatingEnvelope', 'type_set': 'sensor.boolean' }
            self._redback_entities.append(data_dict)
            data_dict = {'value': None,'entity_name': 'op_env_active_reported_start_datetime', 'device_id': device_id, 'device_type': 'OperatingEnvelope', 'type_set': 'sensor.datetime' }
            self._redback_entities.append(data_dict)
            data_dict = {'value': None,'entity_name': 'op_env_active_reported_finished_datetime', 'device_id': device_id, 'device_type': 'OperatingEnvelope', 'type_set': 'sensor.datetime' }
            self._redback_entities.append(data_dict)
            data_dict = {'value': None,'entity_name': 'op_env_active_status', 'device_id': device_id, 'device_type': 'OperatingEnvelope', 'type_set': 'sensor.string' }
            self._redback_entities.append(data_dict)
        else:
            data_dict = {'value': self._redback_op_env_active[site], 'entity_name': 'op_env_active_now', 'device_id': device_id, 'device_type': 'OperatingEnvelope', 'type_set': 'sensor.string' }
            self._redback_entities.append(data_dict)
            data_dict = {'value': data['EventId'],'entity_name': 'op_env_active_event_id', 'device_id': device_id, 'device_type': 'OperatingEnvelope', 'type_set': 'sensor.string' }
            self._redback_entities.append(data_dict)
            data_dict = {'value': data['Nmi'],'entity_name': 'op_env_active_nmi', 'device_id': device_id, 'device_type': 'OperatingEnvelope', 'type_set': 'sensor.string' }
            self._redback_entities.append(data_dict)
            data_dict = {'value': data['SiteId'],'entity_name': 'op_env_active_site_id', 'device_id': device_id, 'device_type': 'OperatingEnvelope', 'type_set': 'sensor.string' }
            self._redback_entities.append(data_dict)
            data_dict = {'value': data['StartAtUtc'],'entity_name': 'op_env_active_start_datetime', 'device_id': device_id, 'device_type': 'OperatingEnvelope', 'type_set': 'sensor.datetime' }
            self._redback_entities.append(data_dict)
            data_dict = {'value': data['EndAtUtc'],'entity_name': 'op_env_active_end_datetime', 'device_id': device_id, 'device_type': 'OperatingEnvelope', 'type_set': 'sensor.datetime' }
            self._redback_entities.append(data_dict)
            data_dict = {'value': data['MaxImportPowerW'],'entity_name': 'op_env_active_max_import_power_w', 'device_id': device_id, 'device_type': 'OperatingEnvelope', 'type_set': 'sensor.integer' }
            self._redback_entities.append(data_dict)
            data_dict = {'value': data['MaxExportPowerW'],'entity_name': 'op_env_active_max_export_power_w', 'device_id': device_id, 'device_type': 'OperatingEnvelope', 'type_set': 'sensor.integer' }
            self._redback_entities.append(data_dict)
            data_dict = {'value': data['MaxDischargePowerW'],'entity_name': 'op_env_active_max_discharge_power_w', 'device_id': device_id, 'device_type': 'OperatingEnvelope', 'type_set': 'sensor.integer' }
            self._redback_entities.append(data_dict)
            data_dict = {'value': data['MaxChargePowerW'],'entity_name': 'op_env_active_max_charge_power_w', 'device_id': device_id, 'device_type': 'OperatingEnvelope', 'type_set': 'sensor.integer' }
            self._redback_entities.append(data_dict)
            data_dict = {'value': data['MaxGenerationPowerVA'],'entity_name': 'op_env_active_max_generation_power_va', 'device_id': device_id, 'device_type': 'OperatingEnvelope', 'type_set': 'sensor.integer' }
            self._redback_entities.append(data_dict)
            data_dict = {'value': data['IsNetworkLevel'],'entity_name': 'op_env_active_is_network_level', 'device_id': device_id, 'device_type': 'OperatingEnvelope', 'type_set': 'sensor.boolean' }
            self._redback_entities.append(data_dict)
            data_dict = {'value': data['ReportedStartUtc'],'entity_name': 'op_env_active_reported_start_datetime', 'device_id': device_id, 'device_type': 'OperatingEnvelope', 'type_set': 'sensor.datetime' }
            self._redback_entities.append(data_dict)
            data_dict = {'value': data['ReportedFinishUtc'],'entity_name': 'op_env_active_reported_finished_datetime', 'device_id': device_id, 'device_type': 'OperatingEnvelope', 'type_set': 'sensor.datetime' }
            self._redback_entities.append(data_dict)
            data_dict = {'value': data['Status'],'entity_name': 'op_env_active_status', 'device_id': device_id, 'device_type': 'OperatingEnvelope', 'type_set': 'sensor.string' }
            self._redback_entities.append(data_dict)
        return

    async def _add_selected_schedule(self, data):
        id_temp = data['Data']['Nodes'][0]['StaticData']['Id']
        id_temp = id_temp[-4:] + 'inv'
        id_temp = id_temp.lower()
        if self._redback_schedule_selected[id_temp]['schedule_selector'] is not None:
            #add schedule to entities
            for schedule in self._redback_schedules:
                if schedule['schedule_selector'] == self._redback_schedule_selected[id_temp]['schedule_selector']:
                    data_dict = {'value': schedule['start_time_utc'],'entity_name': 'scheduled_start_time', 'device_id': id_temp, 'device_type': 'inverter'}
                    self._redback_entities.append(data_dict)
                    data_dict = {'value': schedule['end_time'],'entity_name': 'scheduled_finish_time', 'device_id': id_temp, 'device_type': 'inverter'}
                    self._redback_entities.append(data_dict)
                    data_dict = {'value': schedule['duration'],'entity_name': 'scheduled_duration', 'device_id': id_temp, 'device_type': 'inverter'}
                    self._redback_entities.append(data_dict)
                    data_dict = {'value': schedule['power_w'],'entity_name': 'scheduled_power_w', 'device_id': id_temp, 'device_type': 'inverter'}
                    self._redback_entities.append(data_dict)
                    data_dict = {'value': schedule['inverter_mode'],'entity_name': 'scheduled_inverter_mode', 'device_id': id_temp, 'device_type': 'inverter'}
                    self._redback_entities.append(data_dict)
        else:
            data_dict = {'value': None,'entity_name': 'scheduled_start_time', 'device_id': id_temp, 'device_type': 'inverter'}
            self._redback_entities.append(data_dict)
            data_dict = {'value': None,'entity_name': 'scheduled_finish_time', 'device_id': id_temp, 'device_type': 'inverter'}
            self._redback_entities.append(data_dict)
            data_dict = {'value': 0,'entity_name': 'scheduled_duration', 'device_id': id_temp, 'device_type': 'inverter'}
            self._redback_entities.append(data_dict)
            data_dict = {'value': 0,'entity_name': 'scheduled_power_w', 'device_id': id_temp, 'device_type': 'inverter'}
            self._redback_entities.append(data_dict)
            data_dict = {'value': 'ChargeBattery','entity_name': 'scheduled_inverter_mode', 'device_id': id_temp, 'device_type': 'inverter'}
            self._redback_entities.append(data_dict)
        return

    async def _add_selected_op_env_entities(self, site, device_id):
        """add selected operating envelope to entities"""
        if self._redback_op_env_selected[device_id]['schedule_selector'] is not None:
            #add op_env to entities
            for op_env in self._redback_open_env_data:
                if op_env['data']['schedule_selector'] == self._redback_op_env_selected[device_id]['schedule_selector']:
                    data_dict = {'value': op_env['data']['StartAtUtc'],'entity_name': 'op_env_selected_start_time', 'device_id': device_id, 'device_type': 'OperationEnvelope'}
                    self._redback_entities.append(data_dict)
                    data_dict = {'value': op_env['data']['EndAtUtc'],'entity_name': 'op_env_selected_end_time', 'device_id': device_id, 'device_type': 'OperationEnvelope'}
                    self._redback_entities.append(data_dict)
                    data_dict = {'value': op_env['data']['EventId'],'entity_name': 'op_env_selected_event_id', 'device_id': device_id, 'device_type': 'OperationEnvelope'}
                    self._redback_entities.append(data_dict)
                    data_dict = {'value': op_env['data']['Nmi'],'entity_name': 'op_env_selected_nmi', 'device_id': device_id, 'device_type': 'OperationEnvelope'}
                    self._redback_entities.append(data_dict)
                    data_dict = {'value': op_env['data']['SiteId'],'entity_name': 'op_env_selected_site_id', 'device_id': device_id, 'device_type': 'OperationEnvelope'}
                    self._redback_entities.append(data_dict)
                    data_dict = {'value': op_env['data']['MaxImportPowerW'],'entity_name': 'op_env_selected_max_import_power_w', 'device_id': device_id, 'device_type': 'OperationEnvelope'}
                    self._redback_entities.append(data_dict)
                    data_dict = {'value': op_env['data']['MaxExportPowerW'],'entity_name': 'op_env_selected_max_export_power_w', 'device_id': device_id, 'device_type': 'OperationEnvelope'}
                    self._redback_entities.append(data_dict)
                    data_dict = {'value': op_env['data']['MaxDischargePowerW'],'entity_name': 'op_env_selected_max_discharge_power_w', 'device_id': device_id, 'device_type': 'OperationEnvelope'}
                    self._redback_entities.append(data_dict)
                    data_dict = {'value': op_env['data']['MaxChargePowerW'],'entity_name': 'op_env_selected_max_charge_power_w', 'device_id': device_id, 'device_type': 'OperationEnvelope'}
                    self._redback_entities.append(data_dict)
                    data_dict = {'value': op_env['data']['MaxGenerationPowerVA'],'entity_name': 'op_env_selected_max_generation_power_va', 'device_id': device_id, 'device_type': 'OperationEnvelope'}
                    self._redback_entities.append(data_dict)
                    data_dict = {'value': op_env['data']['Status'],'entity_name': 'op_env_selected_status', 'device_id': device_id, 'device_type': 'OperationEnvelope'}
                    self._redback_entities.append(data_dict)
                    data_dict = {'value': op_env['data']['schedule_selector'],'entity_name': 'op_env_selected_schedule_selector', 'device_id': device_id, 'device_type': 'OperationEnvelope'}
                    self._redback_entities.append(data_dict)
        else:
            data_dict = {'value': None,'entity_name': 'op_env_selected_start_time', 'device_id': device_id, 'device_type': 'OperationEnvelope'}
            self._redback_entities.append(data_dict)
            data_dict = {'value': None,'entity_name': 'op_env_selected_end_time', 'device_id': device_id, 'device_type': 'OperationEnvelope'}
            self._redback_entities.append(data_dict)
            data_dict = {'value': '','entity_name': 'op_env_selected_event_id', 'device_id': device_id, 'device_type': 'OperationEnvelope'}
            self._redback_entities.append(data_dict)
            data_dict = {'value': '','entity_name': 'op_env_selected_nmi', 'device_id': device_id, 'device_type': 'OperationEnvelope'}
            self._redback_entities.append(data_dict)
            data_dict = {'value': '','entity_name': 'op_env_selected_site_id', 'device_id': device_id, 'device_type': 'OperationEnvelope'}
            self._redback_entities.append(data_dict)
            data_dict = {'value': 0,'entity_name': 'op_env_selected_max_import_power_w', 'device_id': device_id, 'device_type': 'OperationEnvelope'}
            self._redback_entities.append(data_dict)
            data_dict = {'value': 0,'entity_name': 'op_env_selected_max_export_power_w', 'device_id': device_id, 'device_type': 'OperationEnvelope'}
            self._redback_entities.append(data_dict)
            data_dict = {'value': 0,'entity_name': 'op_env_selected_max_discharge_power_w', 'device_id': device_id, 'device_type': 'OperationEnvelope'}
            self._redback_entities.append(data_dict)
            data_dict = {'value': 0,'entity_name': 'op_env_selected_max_charge_power_w', 'device_id': device_id, 'device_type': 'OperationEnvelope'}
            self._redback_entities.append(data_dict)
            data_dict = {'value': 0,'entity_name': 'op_env_selected_max_generation_power_va', 'device_id': device_id, 'device_type': 'OperationEnvelope'}
            self._redback_entities.append(data_dict)
            data_dict = {'value': '','entity_name': 'op_env_selected_status', 'device_id': device_id, 'device_type': 'OperationEnvelope'}
            self._redback_entities.append(data_dict)
            data_dict = {'value': None,'entity_name': 'op_env_selected_schedule_selector', 'device_id': device_id, 'device_type': 'OperationEnvelope'}
            self._redback_entities.append(data_dict)
        return
