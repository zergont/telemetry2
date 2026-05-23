"""
Добавить определения бит в fault_bitmap регистры из PDF
"PowerCommand 2.x/3.x/PS0500 Modbus Fault Status Bitmaps" (Modbus 3.3_345.pdf).

Затронутые адреса:
  40757  Customer Faults (Modlon)          — bits 0-15
  41400  переименовать → Diesel Fault Bitmap 31, bits 0-15
  41401  Diesel Fault Bitmap 33            — bits 0-15
  41402  Diesel Fault Bitmap 34            — bits 0-15 (bit 6 отсутствует в PDF)
  41403  AT Fault Status Bitmap 2          — bits 0-15
  41404  AT Fault Status Bitmap 3          — bits 0-15
  41405  AT Fault Status Bitmap 4          — bits 0-15
  41406  AT Fault Status Bitmap 5          — bits 0-15
  41407  AT Fault Status Bitmap 6          — bits 0-15
  41408  AT Fault Status Bitmap 7          — bits 0-10
  41409  AT Fault Status Bitmap 8          — bits 0-7
  41416  Diesel Fault Bitmap 35            — bits 0-15 (биты 9,10,14 отсутствуют в PDF)
  41417  Diesel Fault Bitmap 36            — bits 0-15
  41418  Diesel Fault Bitmap 37            — bits 0-15
"""

import json
from pathlib import Path

MAP_FILE = Path(r"C:\Users\folis\source\repos\telemetry2\devices\pcc\map.jsonl")

# ---------------------------------------------------------------------------
UPDATES = {

    # -----------------------------------------------------------------------
    # 40757  Customer Faults (Modlon)  PDF стр. 44-45
    # -----------------------------------------------------------------------
    40757: {
        "bits": {
            "0":  {"name": "ConfigurableInput1",                 "severity": "none"},
            "1":  {"name": "ConfigurableInput2",                 "severity": "none"},
            "2":  {"name": "ConfigurableInput13",                "severity": "none"},
            "3":  {"name": "ConfigurableInput14",                "severity": "none"},
            "4":  {"name": "AUX1010Input1Fault",                 "severity": "warning"},
            "5":  {"name": "AUX1010Input2Fault",                 "severity": "warning"},
            "6":  {"name": "AUX1010Input3Fault",                 "severity": "warning"},
            "7":  {"name": "AUX1010Input4Fault",                 "severity": "warning"},
            "8":  {"name": "AUX1010Input5Fault",                 "severity": "warning"},
            "9":  {"name": "AUX1010Input6Fault",                 "severity": "warning"},
            "10": {"name": "AUX1010Input7Fault",                 "severity": "warning"},
            "11": {"name": "AUX1010Input8Fault",                 "severity": "warning"},
            "12": {"name": "AUX1011Input1Fault",                 "severity": "warning"},
            "13": {"name": "AUX1011Input2Fault",                 "severity": "warning"},
            "14": {"name": "AUX1011Input3Fault",                 "severity": "warning"},
            "15": {"name": "AUX1011Input4Fault",                 "severity": "warning"},
        },
    },

    # -----------------------------------------------------------------------
    # 41400  FaultStatus Bitmap31  PDF стр. 45-46
    # -----------------------------------------------------------------------
    41400: {
        "name": "Diesel Fault Bitmap 31",
        "notes_ru": "16-битная маска ошибок дизельного двигателя #31 (PCC3300, PC 3.x)",
        "bits": {
            "0":  {"name": "ExhaustGasTemperatureDataIncorrect",      "severity": "warning"},
            "1":  {"name": "FuelFilterPressHighAboveNormal",           "severity": "none"},
            "2":  {"name": "InjectorSolenoidDriver1CalibrationError",  "severity": "warning"},
            "3":  {"name": "InjectorSolenoidDriver2CalibrationError",  "severity": "warning"},
            "4":  {"name": "InjectorSolenoidDriver3CalibrationError",  "severity": "warning"},
            "5":  {"name": "InjectorSolenoidDriver4CalibrationError",  "severity": "warning"},
            "6":  {"name": "InjectorSolenoidDriver5CalibrationError",  "severity": "warning"},
            "7":  {"name": "InjectorSolenoidDriver6CalibrationError",  "severity": "warning"},
            "8":  {"name": "J1939Network2DataIncorrect",               "severity": "none"},
            "9":  {"name": "J1939Network3DataIncorrect",               "severity": "none"},
            "10": {"name": "J1939Network4DataIncorrect",               "severity": "none"},
            "11": {"name": "AUX1013CommunicationLostFault",            "severity": "warning"},
            "12": {"name": "AUX1014CommunicationLostFault",            "severity": "warning"},
            "13": {"name": "StarterAirSupplyPressureLow",              "severity": "warning"},
            "14": {"name": "StarterAirTankVolumeLow",                  "severity": "warning"},
            "15": {"name": "AllowStartOverrideActiveConditionExists",  "severity": "warning"},
        },
    },

    # -----------------------------------------------------------------------
    # 41401  Diesel Fault Bitmap 33  PDF стр. 46-47
    # -----------------------------------------------------------------------
    41401: {
        "bits": {
            "0":  {"name": "MaintainECUPowerLampOORLow",                      "severity": "warning"},
            "1":  {"name": "TurbochargerActuatorSWOutOfCalibration",           "severity": "warning"},
            "2":  {"name": "VariableGeometryTurbochargerActuatorSoftware",     "severity": "warning"},
            "3":  {"name": "VGTActuatorDriverCircuitAbnormalUpdateRate",       "severity": "warning"},
            "4":  {"name": "EngineAirFilterDiffPressLeastSevere",              "severity": "warning"},
            "5":  {"name": "FuelFilterDiffPressModeratelySevere",              "severity": "warning"},
            "6":  {"name": "ExhaustGasRecirculationTemperatureError",          "severity": "warning"},
            "7":  {"name": "EngineTorqueLimitFeatureSpecialInstructions",      "severity": "warning"},
            "8":  {"name": "CoolantLevelSensorReceivedNetworkDataInError",     "severity": "warning"},
            "9":  {"name": "CoolantLevelModeratelyLow",                        "severity": "warning"},
            "10": {"name": "EngineFanClutch2ControlCircuitOORHigh",            "severity": "warning"},
            "11": {"name": "EngineFanClutch2ControlCircuitOORLow",             "severity": "warning"},
            "12": {"name": "HPCRFuelPressReliefValveError",                    "severity": "warning"},
            "13": {"name": "FanSpeedHighMostSevereLevel",                      "severity": "warning"},
            "14": {"name": "EngineAirFilterDiffPressureHigh",                  "severity": "warning"},
            "15": {"name": "FanSpeedLowMostSevereLevel",                       "severity": "warning"},
        },
    },

    # -----------------------------------------------------------------------
    # 41402  Diesel Fault Bitmap 34  PDF стр. 47-48  (бит 6 отсутствует)
    # -----------------------------------------------------------------------
    41402: {
        "bits": {
            "0":  {"name": "NOxLimitsExceededConditionExists",            "severity": "warning"},
            "1":  {"name": "EngineWaitToStartLampAbnormal",               "severity": "warning"},
            "2":  {"name": "FanSpeedError",                               "severity": "shutdown_cooldown"},
            "3":  {"name": "MaintainECUPowerLampOORHigh",                 "severity": "warning"},
            "4":  {"name": "HPCRFuelPressureReliefValveOORHigh",          "severity": "warning"},
            "5":  {"name": "HPCRFuelPressureReliefValveOORLow",           "severity": "warning"},
            "7":  {"name": "HPCRFuelPressureReliefValveConditionExists",  "severity": "warning"},
            "8":  {"name": "AtLeastOneAckModeratelySevereFault",          "severity": "warning"},
            "9":  {"name": "FuelPumpIntakePressureSensorOORHigh",         "severity": "warning"},
            "10": {"name": "FuelPumpIntakePressureSensorOORLow",          "severity": "warning"},
            "11": {"name": "LowFuelPumpIntakePressure",                   "severity": "warning"},
            "12": {"name": "LowFuelPumpIntakePressureNoneSeverity",       "severity": "none"},
            "13": {"name": "HighFuelPumpIntakePressure",                  "severity": "none"},
            "14": {"name": "UnknownShutdownAtIdle",                       "severity": "shutdown"},
            "15": {"name": "UnknownShutdownAtStartup",                    "severity": "shutdown"},
        },
    },

    # -----------------------------------------------------------------------
    # 41403  AT Fault Status Bitmap 2  PDF стр. 48
    # -----------------------------------------------------------------------
    41403: {
        "bits": {
            "0":  {"name": "AT1OutletNOxSensorCircuitOORLow",            "severity": "warning"},
            "1":  {"name": "AT1DPFIntakeTempSensorCircuitOORLow",        "severity": "warning"},
            "2":  {"name": "AT1DEFTankTempSensorOutOfCalibration",       "severity": "warning"},
            "3":  {"name": "AT1OutletNOxSensorAbnormal",                 "severity": "warning"},
            "4":  {"name": "AT1DEFTankLevelSensorOutOfCalibration",      "severity": "warning"},
            "5":  {"name": "AT1DEFDosingUnitTemperatureError",           "severity": "warning"},
            "6":  {"name": "AT1SCRIntakeTempSensorCircuitOORHigh",       "severity": "warning"},
            "7":  {"name": "AT1SCRIntakeTempSensorCircuitOORLow",        "severity": "warning"},
            "8":  {"name": "AT1SCRIntakeTempSensorError",                "severity": "warning"},
            "9":  {"name": "AT1SCROutletTempSensorCircuitOORHigh",       "severity": "warning"},
            "10": {"name": "AT1SCROutletTempSensorCircuitOORLow",        "severity": "warning"},
            "11": {"name": "AT1SCROutletTempSensorError",                "severity": "warning"},
            "12": {"name": "AT1SCRCatalystSystemMissingCondition",       "severity": "warning"},
            "13": {"name": "AT1SCROutletTemperatureHigh",                "severity": "shutdown"},
            "14": {"name": "AT1WarmUpDOCELow",                          "severity": "warning"},
            "15": {"name": "AT1DEFTankLevelSensorAbnormalRateChange",    "severity": "warning"},
        },
    },

    # -----------------------------------------------------------------------
    # 41404  AT Fault Status Bitmap 3  PDF стр. 48-49
    # -----------------------------------------------------------------------
    41404: {
        "bits": {
            "0":  {"name": "AT1SCRIntakeTempHighMostSevere",          "severity": "shutdown"},
            "1":  {"name": "AT1SCRIntakeTempHighModerateSevere",      "severity": "shutdown_cooldown"},
            "2":  {"name": "AT1SCROutletTemperatureHigh",             "severity": "shutdown_cooldown"},
            "3":  {"name": "AT1DEFLineHeater1CircuitOORHigh",         "severity": "warning"},
            "4":  {"name": "AT1DEFLineHeater1CircuitOORLow",          "severity": "warning"},
            "5":  {"name": "AT1DEFLineHeater2CircuitOORHigh",         "severity": "warning"},
            "6":  {"name": "AT1DEFLineHeater2CircuitOORLow",          "severity": "warning"},
            "7":  {"name": "AT1DEFTankHeaterMechanicalSystemError",   "severity": "warning"},
            "8":  {"name": "AT1DEFLineHeater1OpenCircuit",            "severity": "warning"},
            "9":  {"name": "AT1DEFLineHeater2OpenCircuit",            "severity": "warning"},
            "10": {"name": "ATDEFLineHeater3CircuitOORHigh",          "severity": "warning"},
            "11": {"name": "ATDEFLineHeater3CircuitOORLow",           "severity": "warning"},
            "12": {"name": "ATDEFLineHeater3OpenCircuit",             "severity": "warning"},
            "13": {"name": "LowAT1DEFTankLevel",                     "severity": "warning"},
            "14": {"name": "AT1DEFTankLevelLow",                     "severity": "warning"},
            "15": {"name": "AT1OutletNOxSensorAbnormal2",            "severity": "warning"},
        },
    },

    # -----------------------------------------------------------------------
    # 41405  AT Fault Status Bitmap 4  PDF стр. 49-50
    # -----------------------------------------------------------------------
    41405: {
        "bits": {
            "0":  {"name": "ATDEFTankEmpty",                          "severity": "warning"},
            "1":  {"name": "AT1DEFDosingUnitOORHigh",                "severity": "warning"},
            "2":  {"name": "AT1DEFDosingUnitOORLow",                 "severity": "warning"},
            "3":  {"name": "ATDEFLineHeaterRelayOORHigh",            "severity": "warning"},
            "4":  {"name": "ATDEFLineHeaterRelayOORLow",             "severity": "warning"},
            "5":  {"name": "ATDEFDosingValveOpenCircuit",            "severity": "warning"},
            "6":  {"name": "ATDEFDosingValveMechanicalSystemError",  "severity": "warning"},
            "7":  {"name": "AT1DEFPressureSensorOORHigh",            "severity": "warning"},
            "8":  {"name": "AT1DEFPressureSensorOORLow",             "severity": "warning"},
            "9":  {"name": "AT1DEFPressureSensorLow",                "severity": "warning"},
            "10": {"name": "AT1DEFPressureSensorHigh",               "severity": "warning"},
            "11": {"name": "ATDEFReturnValveOORHigh",                "severity": "warning"},
            "12": {"name": "ATDEFReturnValveOORLow",                 "severity": "warning"},
            "13": {"name": "ATSCRCatalystConversionEfficiencyLow",   "severity": "warning"},
            "14": {"name": "AT1OutletNOxSensorHeaterAbnormal",       "severity": "warning"},
            "15": {"name": "AT1DEFPressureSensorError",              "severity": "warning"},
        },
    },

    # -----------------------------------------------------------------------
    # 41406  AT Fault Status Bitmap 5  PDF стр. 50-51
    # -----------------------------------------------------------------------
    41406: {
        "bits": {
            "0":  {"name": "AT1IntakeNOxSensorHeaterAbnormal",         "severity": "warning"},
            "1":  {"name": "AT1OutletNOxSensorPowerSupplyError",       "severity": "warning"},
            "2":  {"name": "AT1DPFIntakeTemperatureError",             "severity": "shutdown"},
            "3":  {"name": "AT1OutletNOxSensorOutOfCalibration",       "severity": "warning"},
            "4":  {"name": "AT1IntakeNOxSensorAbnormal",               "severity": "warning"},
            "5":  {"name": "AT1DPFIntakeTempMostSevereLevel",          "severity": "warning"},
            "6":  {"name": "AT1IntakeNOxSensorDataNotRational",        "severity": "warning"},
            "7":  {"name": "AT1OutletNOxSensorDataNotRational",        "severity": "warning"},
            "8":  {"name": "AT1DPFIntakeTempModeratelySevereLevel",    "severity": "warning"},
            "9":  {"name": "ATDEFQualityLowModeratelySevereLevel",     "severity": "warning"},
            "10": {"name": "ATDEFQualityError",                        "severity": "warning"},
            "11": {"name": "ATDEFQualitySensorMechanicalSystemError",  "severity": "warning"},
            "12": {"name": "AT1DPFIntakeTempLeastSevereLevel",         "severity": "warning"},
            "13": {"name": "ATDEFQualitySensorDataError",              "severity": "warning"},
            "14": {"name": "ATDPFTemperatureSensorModuleAbnormal",     "severity": "warning"},
            "15": {"name": "ATSCRTemperatureSensorModuleAbnormal",     "severity": "warning"},
        },
    },

    # -----------------------------------------------------------------------
    # 41407  AT Fault Status Bitmap 6  PDF стр. 51-52
    # -----------------------------------------------------------------------
    41407: {
        "bits": {
            "0":  {"name": "AT1DEFDosingUnitHeaterRelayOORHigh",      "severity": "warning"},
            "1":  {"name": "AT1DEFDosingUnitHeaterRelayOORLow",       "severity": "warning"},
            "2":  {"name": "ATDEFReturnValveMechanicalSystemError",   "severity": "warning"},
            "3":  {"name": "ATDEFTempSensorModuleBadDevice",          "severity": "warning"},
            "4":  {"name": "ATSCRTempSensorModuleBadDevice",          "severity": "warning"},
            "5":  {"name": "ATDPFTempSensorModuleOORHigh",            "severity": "warning"},
            "6":  {"name": "ATDPFTempSensorModuleOORLow",             "severity": "warning"},
            "7":  {"name": "ATDPFTempSensorRootCauseNotKnown",        "severity": "warning"},
            "8":  {"name": "ATSCRTempSensorModuleOORHigh",            "severity": "warning"},
            "9":  {"name": "ATSCRTempSensorModuleOORLow",             "severity": "warning"},
            "10": {"name": "ATSCRTempSensorModuleHigh",               "severity": "warning"},
            "11": {"name": "AT1DEFDosingUnitHeaterOORHigh",           "severity": "warning"},
            "12": {"name": "AT1DEFDosingUnitHeaterOORLow",            "severity": "warning"},
            "13": {"name": "SCRTemperatureLow",                       "severity": "warning"},
            "14": {"name": "ATDPFTempSensorModuleHigh",               "severity": "warning"},
            "15": {"name": "AT1DOCSystemSpecialInstruction",          "severity": "shutdown_cooldown"},
        },
    },

    # -----------------------------------------------------------------------
    # 41408  AT Fault Status Bitmap 7  PDF стр. 52  (биты 5 отсутствует)
    # -----------------------------------------------------------------------
    41408: {
        "bits": {
            "0":  {"name": "ATDEFQualityReceivedNetworkDataError",        "severity": "warning"},
            "1":  {"name": "AT1DEFTemperature2Abnormal",                  "severity": "warning"},
            "2":  {"name": "ATSystemNormalShutdownRequest",               "severity": "shutdown_cooldown"},
            "3":  {"name": "ATSystemDatalinkDegraded",                    "severity": "warning"},
            "4":  {"name": "AT1DEFDosingTemperatureAbnormal",             "severity": "warning"},
            "6":  {"name": "ATSCRTempSensorModuleRootCauseUnknown",       "severity": "warning"},
            "7":  {"name": "ATDEFQualityAbnormal",                        "severity": "warning"},
            "8":  {"name": "AT1DEFTankTemperatureAbnormal",               "severity": "warning"},
            "9":  {"name": "AT1SCRCatalystSystemSpecialInstruction",      "severity": "shutdown"},
            "10": {"name": "ATSCRActualDosingReagentQuantityLow",         "severity": "warning"},
        },
    },

    # -----------------------------------------------------------------------
    # 41409  AT Fault Status Bitmap 8  PDF стр. 52
    # -----------------------------------------------------------------------
    41409: {
        "bits": {
            "0": {"name": "AT1DEFTankLevelSensorRootCauseUnknown",  "severity": "warning"},
            "1": {"name": "ATDEFQualitySensorOpenCircuit",           "severity": "warning"},
            "2": {"name": "ATDEFQualitySensorShortCircuit",          "severity": "warning"},
            "3": {"name": "AT1DEFTemperature2SensorOpenCircuit",     "severity": "warning"},
            "4": {"name": "AT1DEFTemperature2SensorShortCircuit",    "severity": "warning"},
            "5": {"name": "AT1DEFTemperature2RootCauseUnknown",      "severity": "warning"},
            "6": {"name": "AT1DEFPropertyRootCauseUnknown",          "severity": "warning"},
            "7": {"name": "ATDEFReplenishmentFailure",               "severity": "warning"},
        },
    },

    # -----------------------------------------------------------------------
    # 41416  Diesel Fault Bitmap 35  PDF стр. 53  (биты 9,10,14 отсутствуют)
    # -----------------------------------------------------------------------
    41416: {
        "bits": {
            "0":  {"name": "EngineWaitToStartLampConditionExists",    "severity": "none"},
            "1":  {"name": "WaterInFuelIndicator2SensorOORHigh",      "severity": "warning"},
            "2":  {"name": "WaterInFuelIndicator2SensorOORLow",       "severity": "warning"},
            "3":  {"name": "HighWaterInFuelIndicator2Warning",        "severity": "warning"},
            "4":  {"name": "HighWaterInFuelIndicator2Shutdown",       "severity": "shutdown"},
            "5":  {"name": "DeadBatteryWarning",                      "severity": "warning"},
            "6":  {"name": "PrimaryStartingSystemFailed",             "severity": "warning"},
            "7":  {"name": "IMR2PressureSensorCircuitShortedHigh",    "severity": "warning"},
            "8":  {"name": "IMR2PressureSensorCircuitShortedLow",     "severity": "warning"},
            "11": {"name": "DPF1ConditionsNotMetForActiveRegen",      "severity": "warning"},
            "12": {"name": "IntakeThrottleSensorCircuitShortedHigh",  "severity": "warning"},
            "13": {"name": "IntakeThrottleSensorCircuitShortedLow",   "severity": "warning"},
            "15": {"name": "VehicleIDNumberOutOfCalibration",         "severity": "warning"},
        },
    },

    # -----------------------------------------------------------------------
    # 41417  Diesel Fault Bitmap 36  PDF стр. 53-54
    # -----------------------------------------------------------------------
    41417: {
        "bits": {
            "0":  {"name": "HighECMInternalTemperature",                   "severity": "warning"},
            "1":  {"name": "MemoryWriteFailed",                            "severity": "warning"},
            "2":  {"name": "PowerLostDuringMemorySave",                    "severity": "warning"},
            "3":  {"name": "AutoTrimsSaveFailed",                          "severity": "warning"},
            "4":  {"name": "ManualTrimsSaveFailed",                        "severity": "warning"},
            "5":  {"name": "ParallelingCableNotDetectedConditionExists",   "severity": "none"},
            "6":  {"name": "ASOPositionSwitchMismatch",                    "severity": "shutdown"},
            "7":  {"name": "MaxTimeExceededSinceLastASOVSystemTest",       "severity": "warning"},
            "8":  {"name": "ASOSolenoidOutOfRangeHigh",                    "severity": "warning"},
            "9":  {"name": "ASOSolenoidOutOfRangeLow",                     "severity": "warning"},
            "10": {"name": "EngineAirShutoffMechanicalSystemNotResponding","severity": "shutdown"},
            "11": {"name": "ASOVEStopActive",                              "severity": "shutdown"},
            "12": {"name": "IntakeManifoldPressureBankImbalance",          "severity": "shutdown"},
            "13": {"name": "IntakeManifoldVacuumDetectedBank1",            "severity": "shutdown"},
            "14": {"name": "IntakeManifoldVacuumDetectedBank2",            "severity": "shutdown"},
            "15": {"name": "SecondaryEngineOverspeed",                     "severity": "shutdown"},
        },
    },

    # -----------------------------------------------------------------------
    # 41418  Diesel Fault Bitmap 37  PDF стр. 54-55
    # -----------------------------------------------------------------------
    41418: {
        "bits": {
            "0":  {"name": "ThrottleDriverFeedbackHighError1",             "severity": "warning"},
            "1":  {"name": "ThrottleDriverFeedbackHighError2",             "severity": "warning"},
            "2":  {"name": "ElectronicThrottleControlActuatorNotResponding","severity": "warning"},
            "3":  {"name": "EngineWitnessTestAbortConditionExists",        "severity": "warning"},
            "4":  {"name": "FailToStop",                                   "severity": "shutdown"},
            "5":  {"name": "CriticalCENNotAccessibleError",                "severity": "shutdown_cooldown"},
            "6":  {"name": "J1939DataLink2EngineNetworkAbnormal",          "severity": "shutdown"},
            "7":  {"name": "J1939DataLink2EngineNetworkNoDataReceived",    "severity": "warning"},
            "8":  {"name": "J1939DataLink2EngineNetworkSpecialInstructions","severity": "shutdown"},
            "9":  {"name": "NominalVoltageSetupOOR",                       "severity": "shutdown"},
            "10": {"name": "AtLeastOneUnclearedECSShutdownFaultExists",    "severity": "warning"},
            "11": {"name": "FuelPumpDeliveryPressure",                     "severity": "warning"},
            "12": {"name": "ExhaustGasTemperatureBankImbalance",           "severity": "warning"},
            "13": {"name": "ExhaustGasTemperatureShutdown",                "severity": "shutdown"},
            "14": {"name": "EngineFuelDeliveryPressureShutdown",           "severity": "shutdown"},
            "15": {"name": "EngineDieselFuelMeteringValvePressureError",   "severity": "warning"},
        },
    },
}


def main():
    entries = []
    with open(MAP_FILE, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))

    idx = {(e['reg_type'], e['addr']): i for i, e in enumerate(entries)}

    updated = 0
    skipped = []

    for addr, upd in UPDATES.items():
        key = ('holding', addr)
        if key not in idx:
            skipped.append(addr)
            continue
        i = idx[key]
        e = entries[i]
        if 'name' in upd:
            e['name'] = upd['name']
        if 'notes_ru' in upd:
            e['notes_ru'] = upd['notes_ru']
        e['unit'] = 'fault_bitmap'
        e['bits'] = upd['bits']
        updated += 1

    if skipped:
        print(f"WARNING: адреса не найдены: {skipped}")

    with open(MAP_FILE, 'w', encoding='utf-8', newline='\n') as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + '\n')

    print(f"Обновлено {updated} регистров:")
    for addr in sorted(UPDATES):
        n = UPDATES[addr].get('name', '')
        bits_n = len(UPDATES[addr]['bits'])
        name_str = f"-> {n}  " if n else ''
        print(f"  addr={addr}  {name_str}bits={bits_n}")

    # Итоговая статистика
    entries2 = [json.loads(l) for l in open(MAP_FILE, encoding='utf-8') if l.strip()]
    bitmaps = [e for e in entries2 if e.get('unit') == 'fault_bitmap']
    with_bits  = sum(1 for e in bitmaps if e.get('bits'))
    empty_bits = sum(1 for e in bitmaps if 'bits' in e and not e['bits'])
    no_bits    = sum(1 for e in bitmaps if 'bits' not in e)
    print(f"\nfault_bitmap итого: {len(bitmaps)} | с битами: {with_bits} | пустые: {empty_bits} | нет поля: {no_bits}")


if __name__ == '__main__':
    main()
