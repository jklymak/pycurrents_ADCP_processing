"""
author: Hana Hourston
"""

import os
import numpy as np
import xarray as xr
import matplotlib.pyplot as plt
import warnings
import pandas as pd
import gsw
from datetime import datetime, timezone
from pycurrents_ADCP_processing import plot_westcoast_nc_LX as pwl


def date2ns(date):
    # Convert datetime64 object to nanoseconds since 1970-01-01
    return pd.to_datetime(date).value


def add_attrs_prexmcat(dataset, name_ctd):
    """
    Adds attributes to CTD pressure variable. dataset should already include the PREXMCAT variable
    Inputs:
        - dataset: dataset-type object created by reading in a netCDF ADCP file with the xarray package
        - name_ctd: string containing the name of the CTD file whose pressure data was used
    Outputs:
        None
    """

    var = dataset.PREXMCAT
    var.encoding['dtype'] = 'float32'
    var.attrs['units'] = dataset.PRESPR01.units
    var.attrs['_FillValue'] = dataset.PRESPR01.encoding['_FillValue']
    var.attrs['long_name'] = 'pressure'
    var.attrs['sensor_type'] = 'adcp'
    var.attrs['sensor_depth'] = dataset.PRESPR01.sensor_depth
    var.attrs['serial_number'] = dataset.serial_number
    # var.attrs['sdn_parameter_name'] = 'Pressure (spatial co-ordinate) exerted by the water body by profiling ' \
    #                                  'pressure sensor and corrected to read zero at sea level'
    var.attrs['ctd_file_used_for_pressure'] = os.path.basename(name_ctd)
    var.attrs['sdn_parameter_name'] = 'Pressure (measured variable) exerted by the water body by semi-fixed ' \
                                      'moored SBE MicroCAT'
    var.attrs['sdn_uom_urn'] = 'SDN:P06::UPDB'
    var.attrs['sdn_uom_name'] = 'Decibars'
    var.attrs['standard_name'] = 'sea_water_pressure'
    var.attrs['data_min'] = np.nanmin(var.data)
    var.attrs['data_max'] = np.nanmax(var.data)

    return


def add_pressure_ctd(nc_adcp: xr.Dataset, nc_ctd: xr.Dataset):
    """
    Function for calculating ADCP pressure from SBE (Sea-Bird CTD) pressure on the same mooring line
    Inputs:
        - nc_adcp: dataset-type object created by reading in a netCDF ADCP file with the xarray package
        - nc_ctd: dataset-type object created by reading in a netCDF CTD file with the xarray package
    Outputs:
        - out_adcp_dataset: a new dataset-type object, the same as nc_adcp but with the new pressure
                            variable PREXMCAT derived from CTD pressure.
    """

    # Initialize new pressure array with nans
    pres_adcp_from_ctd = np.empty(shape=nc_adcp.PRESPR01.data.shape, dtype='float32')
    pres_adcp_from_ctd[:] = np.nan
    print(pres_adcp_from_ctd.shape)

    min2sec = 60
    sec2nsec = 1e9
    min2nano = min2sec * sec2nsec

    # Calculate ratio of sampling time increments
    time_increment_adcp = date2ns(nc_adcp.time.data[1]) - date2ns(nc_adcp.time.data[0])
    time_increment_ctd = date2ns(nc_ctd.time.data[1]) - date2ns(nc_ctd.time.data[0])
    time_increment_ratio = time_increment_adcp / time_increment_ctd
    # print(time_increment_ratio)

    if np.round(time_increment_ratio, decimals=1) < 1:
        if np.round(time_increment_ratio, decimals=1) == 1/1.5:
            index_increment_adcp = 2
            index_increment_ctd = 3
        else:
            # time_increment_ratio = int(np.round(1 / time_increment_ratio, decimals=0))
            index_increment_adcp = 1
            index_increment_ctd = int(np.round(1 / time_increment_ratio, decimals=0))
    else:
        if np.round(time_increment_ratio, decimals=1) == 1.5:
            # To account for time ratios of 1.5 (e.g. adcp every 15 min, ctd every 10 min)
            # time_increment_ratio = int(np.round(2 * time_increment_ratio, decimals=0))
            index_increment_adcp = 3
            index_increment_ctd = 2
        else:
            # time_increment_ratio = int(np.round(time_increment_ratio, decimals=0))
            index_increment_adcp = int(np.round(time_increment_ratio, decimals=0))
            index_increment_ctd = 1

    print('Index increment for adcp =', index_increment_adcp)
    print('Index increment for ctd =', index_increment_ctd)
    max_increment = index_increment_adcp if index_increment_adcp > index_increment_ctd else index_increment_ctd

    # Try finding index of start time of one time in the other time range from [0] up to [time_increment_ratio]
    # and index of end time of one time in the other time range from [-1] up to [-time_increment_ratio]

    # Initialize indices
    start_index_in_CTD = -9
    end_index_in_CTD = -9
    start_index_in_ADCP = -9
    end_index_in_ADCP = -9

    # Due to differences in sampling time intervals between instruments, may need to take later start time
    # and earlier end time, in order to match up times as closely as possible
    earliest_start_index = -9
    latest_end_index = -9

    # Step 1

    # Find index of first time, either in the ctd time range or in the adcp time range
    # Test if CTD time starts before the ADCP time
    if date2ns(nc_ctd.time.data[0]) < date2ns(nc_adcp.time.data[0]):
        # adcp start time is in ctd time range
        print("CTD start-time earlier than ADCP start-time !")

        for start_index in range(max_increment):
            print(start_index)
            for t_i in range(len(nc_ctd.time.data)):
                # Find the index of the first adcp time measurement in the ctd time range within 4 min
                if np.abs(date2ns(nc_ctd.time.data[t_i]) - date2ns(
                        nc_adcp.time.data[start_index])) < 4 * min2nano:
                    start_index_in_CTD = t_i
                    break
            # Break out of loop if start_index_in_CTD is found
            # Otherwise try the next time in the adcp time range
            if start_index_in_CTD != -9:
                earliest_start_index = start_index  # in CTD time
                break
    else:
        # adcp start time before first ctd time
        print("ADCP start-time earlier than CTD start-time !")

        for start_index in range(max_increment):
            print(start_index)
            for t_j in range(len(nc_adcp.time.data)):
                # Find the index of the first ctd time measurement in the adcp time range within 4 min
                if np.abs(date2ns(nc_adcp.time.data[t_j]) - date2ns(
                        nc_ctd.time.data[start_index])) < 4 * min2nano:
                    start_index_in_ADCP = t_j
                    break
            # Break out of loop if start_index_in_CTD is found
            # Otherwise try the next time in the adcp time range
            if start_index_in_ADCP != -9:
                earliest_start_index = start_index  # in ADCP time
                break

    # Find index of last time, either in the ctd time range or in the adcp time range
    # end_index is the index where the earlier end time matches a time in the other time range
    if date2ns(nc_ctd.time.data[-1]) > date2ns(nc_adcp.time.data[-1]):
        print("CTD end-time later than ADCP end-time !")
        for end_index in range(1, max_increment + 1):
            for t_i in range(len(nc_ctd.time.data)):
                # Find the index of the last adcp time measurement in the ctd time range within 4 min
                if np.abs(date2ns(nc_ctd.time.data[t_i]) - date2ns(
                        nc_adcp.time.data[-end_index])) < 4 * min2nano:
                    end_index_in_CTD = t_i
                    break
            # Break out of loop if start_index_in_CTD is found
            # Otherwise try the next time in the adcp time range
            if end_index_in_CTD != -9:
                latest_end_index = -end_index  # in CTD time
                break
    else:
        # adcp end time is after last ctd time
        print("SBE end-time earlier than ADCP end-time !")

        for end_index in range(1, max_increment + 1):
            print(end_index)
            for t_j in range(len(nc_adcp.time.data)):
                if np.abs(date2ns(nc_adcp.time.data[t_j]) - date2ns(
                        nc_ctd.time.data[-end_index])) < 4 * min2nano:
                    end_index_in_ADCP = t_j
                    break
            # Break out of loop if start_index_in_CTD is found
            # Otherwise try the next time in the adcp time range
            if end_index_in_ADCP != -9:
                latest_end_index = -end_index  # in ADCP time
                break

    print('start_index_in_CTD:', start_index_in_CTD, sep=' ')
    print('end_index_in_CTD:', end_index_in_CTD, sep=' ')
    print('start_index_in_ADCP:', start_index_in_ADCP, sep=' ')
    print('end_index_in_ADCP:', end_index_in_ADCP, sep=' ')

    print('earliest_start_index:', earliest_start_index, sep=' ')
    print('latest_end_index:', latest_end_index, sep=' ')

    if earliest_start_index == -9 or latest_end_index == -9:
        IndexError('Invalid earliest start index or latest end index')

    # Step 2

    # Fill in pressure array that was initialized with nans
    if start_index_in_CTD != -9:
        print('Start adcp time is in ctd time range')
        if end_index_in_CTD != -9:
            print('End adcp time is in ctd time range')
            pres_adcp_from_ctd[earliest_start_index:latest_end_index
                               :index_increment_ctd] = nc_ctd.PRESPR01.data[
                                                       start_index_in_ADCP:end_index_in_ADCP:index_increment_adcp]
        else:
            print('End adcp time is after ctd time range')
            pres_adcp_from_ctd[earliest_start_index:end_index_in_ADCP
                               :index_increment_ctd] = nc_ctd.PRESPR01.data[
                                                       start_index_in_CTD:latest_end_index:index_increment_adcp]
    else:
        print('adcp time starts before ctd time range')
        if end_index_in_CTD != -9:
            print('adcp end time is within ctd time range')
            pres_adcp_from_ctd[start_index_in_ADCP:latest_end_index
                               :index_increment_ctd] = nc_ctd.PRESPR01.data[
                                                       earliest_start_index:end_index_in_CTD:index_increment_adcp]
        else:
            # End ctd time is in adcp time range
            print('adcp end time is after ctd time range')
            pres_adcp_from_ctd[start_index_in_ADCP:end_index_in_ADCP
                               :index_increment_ctd] = nc_ctd.PRESPR01.data[
                                                       earliest_start_index:latest_end_index:index_increment_adcp]

    # Step 3

    # Apply depth corrections to new pressure
    # Calculate depth difference between ADCP and SBE; positive if ADCP deeper than SBE
    depth_diff = nc_adcp.instrument_depth - nc_ctd.instrument_depth.data  # meters
    print(depth_diff)
    pres_adcp_from_ctd = pres_adcp_from_ctd + np.round(depth_diff, decimals=1)

    out_adcp_dataset = nc_adcp.assign(PREXMCAT=(('time'), pres_adcp_from_ctd))
    print('Created new xarray dataset object containing CTD-derived pressure')

    add_attrs_prexmcat(out_adcp_dataset, name_ctd=str(nc_ctd.filename.data))
    print('Added attributes to PREXMCAT')

    out_adcp_dataset.attrs['processing_history'] += f' CTD pressure data from file {str(nc_ctd.filename.data)} ' \
                                                    f'merged with input ADCP dataset.'

    return out_adcp_dataset


def flag_by_pres(d, use_prexmcat=False):
    """
    For flagging velocity data by bins where pressure is negative at each time step. This function
    is for upward-facing instruments only.
    Inputs:
        - d: dataset-type object created by reading in a netCDF ADCP file with the xarray package
        - use_prexmcat: Defaults to False, which uses PRESPR01. True means PREXMCAT will be used.
    Outputs:
        - bad_bin_list: an array containing the index of the first bad bin at each time step;
                        "bad bins" are designated as having negative pressure or are below ocean
                        floor depth
    """

    if use_prexmcat:
        print('Using PREXMCAT as pressure data ...')
        pressure = d.PREXMCAT
    else:
        print('Using PRESPR01 as pressure data ...')
        pressure = d.PRESPR01

    # Obtain the number of leading and trailing ensembles that were set to nans during L1 processing
    # start_end_L1 = plot_westcoast_nc_LX.get_L1_start_end(ncdata=d)
    # print('Start and end indices between nans from L1:', start_end_L1[0], start_end_L1[1], sep=' ')

    # List of indices where bins start to have negative pressure
    # bad_bin_list = np.zeros(shape=d.time.data.shape, dtype='int32') #initialize with zeros
    # bad_bin_list[start_end_L1[0]:start_end_L1[1]] = -1 #assume no bad bins in this range; index=-1

    # Flag by negative pressure timestep by timestep
    # for t_i in range(start_end_L1[0], start_end_L1[1]):
    #     flag = 0
    #     # Iterate through bins
    #     for b_i in range(len(d.distance.data)):  # bin with index 0 == 1st bin
    #         # Calculate pressure at each bin depth by subtracting each bin distance from pressure at time step
    #         bin_pres = pressure.data[t_i] - d.distance.data[b_i]
    #         if bin_pres < 0:
    #             # Identify first bin index with negative pressure
    #             bad_bin_1 = b_i
    #             bad_bin_list[t_i] = bad_bin_1
    #             flag += 1
    #         if flag != 0:
    #             break

    pres_2d = np.vstack((pressure.data,) * len(d.distance.data))
    dist_2d = np.vstack((d.distance.data,) * len(pressure.data)).transpose()
    bin_pres = pres_2d - dist_2d

    # Flag velocity data
    flag_vb = pwl.vb_flag(d)
    if d.instrumentSubtype == 'Sentinel V' and flag_vb == 0:
        vels_QC = [d.LCEWAP01_QC.data, d.LCNSAP01_QC.data, d.LCNSAP01_QC.data, d.LRZUVP01_QC.data]
    else:
        vels_QC = [d.LCEWAP01_QC.data, d.LCNSAP01_QC.data, d.LCNSAP01_QC.data]

    # for v_QC in vels_QC:
    #     for t_i in range(start_end_L1[0], start_end_L1[1]):
    #         # Skip time steps with no bad bins
    #         if bad_bin_list[t_i] != -1:
    #             v_QC[bad_bin_list[t_i]:, t_i] = 4  # bad_value flag=4

    for v_QC in vels_QC:
        v_QC[bin_pres < 0] = 4

    d.attrs['processing_history'] = d.processing_history + " Level 2 processing was performed on the data."
    d.attrs['processing_history'] = d.processing_history + " Bins with negative pressure (i.e. were located above" \
                                                           " sea level) were flagged as bad_value" \
                                                           " timestep by timestep."

    # return bad_bin_list
    return


def flag_below_seafloor(d):
    """
    Flag by depth when bin depth > ocean depth, timestep by timestep. This function is for
    downward-facing instruments only.
    Inputs:
        - d: dataset-type object created by reading in a netCDF ADCP file with the xarray package
    Outputs:
        - bad_bin_list: an array containing the index of the first bad bin at each time step;
                        "bad bins" are designated as having negative pressure or are below ocean
                        floor depth
    """

    # Obtain the number of leading and trailing ensembles that were set to nans during L1 processing
    # start_end_L1 = plot_westcoast_nc_LX.get_L1_start_end(ncdata=d)
    # print('Start and end indices between nans from L1:', start_end_L1[0], start_end_L1[1], sep=' ')

    # bad_bin_list = np.zeros(shape=d.time.data.shape, dtype='int32') #initialize with zeros
    # bad_bin_list[start_end_L1[0]:start_end_L1[1]] = -1 #assume no bad bins in range
    # for t_i in range(start_end_L1[0], start_end_L1[1]):
    #     flag = 0
    #     # Find shallowest bin that is within the ocean floor and flag it and all deeper ones as 4 == bad_data
    #     for b_i in range(len(d.distance.data)):
    #         bin_depth = d.instrument_depth + d.distance.data[b_i]
    #         if bin_depth > d.water_depth:
    #             bad_bin_1 = b_i
    #             bad_bin_list[t_i] = bad_bin_1
    #             flag += 1
    #         if flag != 0:
    #             break

    instrument_depth_2d = np.zeros((len(d.distance.data), len(d.time.data)), 'float32')
    instrument_depth_2d[:, :] = d.instrument_depth
    distance_2d = np.vstack((d.distance.data,) * len(d.time.data)).transpose()
    bin_depths = instrument_depth_2d - distance_2d

    # Flag velocity data
    flag_vb = pwl.vb_flag(d)
    if d.instrumentSubtype == 'Sentinel V' and flag_vb == 0:
        vels_QC = [d.LCEWAP01_QC.data, d.LCNSAP01_QC.data, d.LCNSAP01_QC.data, d.LRZUVP01_QC.data]
    else:
        vels_QC = [d.LCEWAP01_QC.data, d.LCNSAP01_QC.data, d.LCNSAP01_QC.data]

    # for v_QC in vels_QC:
    #     for t_i in range(start_end_L1[0], start_end_L1[1]):
    #         # If time is after deployment time and before recovery time, from L1
    #         if bad_bin_list[t_i] != -1:
    #             v_QC[bad_bin_list[t_i]:, t_i] = 4  # bad_value flag=4
    #             v_QC[:bad_bin_list[t_i], t_i] = 2  # probably_good_value flag=2, or good_value flag=1

    for v_QC in vels_QC:
        v_QC[bin_depths > d.water_depth] = 4  # bad_value flag=4

    d.attrs['processing_history'] = d.processing_history + " Level 2 processing was performed on the data."
    d.attrs['processing_history'] = d.processing_history + " Bins below the ocean floor depth were flagged as" \
                                                           " bad_value timestep by timestep."
    d.attrs['processing_history'] = d.processing_history + "The remaining bins were flagged as " \
                                                           "probably_good_value."

    #return bad_bin_list
    return


def flag_by_backsc(d: xr.Dataset):
    """
    Flag where beam-averaged backscatter increases at each time step for upwards-facing ADCPs
    Inputs:
        - d: dataset-type object created by reading in a netCDF ADCP file with the xarray package
        - bad_bin_list: numpy array containing the index of the first "bad" bin (bin where pressure is
                        negative) obtained from the function flag_by_pres()
    Outputs:
        - susp_bin_list: an array containing the index of the first suspicious bin at each time step;
                         counting away from the instrument. "Suspicious bins" define bins with
                         backscatter increases.
    """

    # Obtain the number of leading and trailing ensembles that were set to nans during L1 processing
    # From these get the start index after the nans and the end index before the nans
    # start_end_L1 = plot_westcoast_nc_LX.get_L1_start_end(ncdata=d)
    # print('Start and end indices from L1:', start_end_L1[0], start_end_L1[1], sep=' ')

    # Take beam-averaged backscatter, excluding data from before deployment and after recovery
    # Beam-averaged backscatter is shorter than time series
    flag_vb = pwl.vb_flag(d)
    if d.instrumentSubtype == 'Sentinel V' and flag_vb == 0:
        # Include amplitude intensity from vertical 5th beam
        amp_beam_avg = np.nanmean([d.TNIHCE01.data[:, :],
                                   d.TNIHCE02.data[:, :],
                                   d.TNIHCE03.data[:, :],
                                   d.TNIHCE04.data[:, :],
                                   d.TNIHCE05.data[:, :]], axis=0)
    else:
        amp_beam_avg = np.nanmean([d.TNIHCE01.data[:, :],
                                   d.TNIHCE02.data[:, :],
                                   d.TNIHCE03.data[:, :],
                                   d.TNIHCE04.data[:, :]], axis=0)

    # Then determine bin where beam-averaged backscatter increases for each timestep
    # susp_bin_list = np.zeros(shape=d.time.data.shape, dtype='int32') #initialize with zeros
    # susp_bin_list[start_end_L1[0]:start_end_L1[1]] = -1 #assume no suspicious bins in range

    # Iterate through time stamps between the deployment and recovery times
    # for t_i in range(start_end_L1[0], start_end_L1[1]):
    #     flag = 0
    #     # Iterate through bin numbers. Start at index=2 because sometimes one-bin increases occur in the first
    #     # 2 bins closest to ADCP, not near the surface.
    #     for b_i in range(2, len(d.distance.data)):
    #         if amp_beam_avg[b_i, t_i - start_end_L1[0]] > amp_beam_avg[b_i - 1, t_i - start_end_L1[0]]:
    #             # Index of first suspicious bin counting away from the instrument
    #             # print(b_i)
    #             susp_bin_list[t_i] = b_i
    #             flag += 1
    #         if flag == 1:
    #             break

    diffs = np.diff(amp_beam_avg, axis=0)
    diffs[0, :] = 0  # to remove misleading increases often observed from the first to second bin
    zeros = np.zeros(len(d.time.data)) #to stack on top of diffs, because the y dim of diffs < y dim of d.distance
    diffs = np.vstack((zeros, diffs))

    # Flag the qc variables
    if d.instrumentSubtype == 'Sentinel V' and flag_vb == 0:
        vels_QC = [d.LCEWAP01_QC.data, d.LCNSAP01_QC.data, d.LCNSAP01_QC.data, d.LRZUVP01_QC.data]
    else:
        vels_QC = [d.LCEWAP01_QC.data, d.LCNSAP01_QC.data, d.LCNSAP01_QC.data]

    # for v_QC in vels_QC:
    #     # Iterate through time stamps
    #     for t_i in range(start_end_L1[0], start_end_L1[1]):
    #         # Iterate through bins
    #         for b_i in range(len(d.distance.data)):
    #             if susp_bin_list[t_i] != -1:
    #                 if bad_bin_list[t_i] != -1:
    #                     v_QC[susp_bin_list[t_i]:bad_bin_list[t_i], t_i] = 3  # probably_bad_value
    #                     v_QC[:susp_bin_list[t_i], t_i] = 2  # probably_good_value flag=2, or good_value flag=1
    #                 else:
    #                     #bad_bin_list[t_i] == -1 so no bad bins
    #                     v_QC[susp_bin_list[t_i]:, t_i] = 3  # probably_bad_value
    #                     v_QC[:susp_bin_list[t_i], t_i] = 2  # probably_good_value flag=2, or good_value flag=1
    #             else:
    #                 #susp_bin_list[t_i] and bad_bin_list[t_i] == -1 so no suspicious and no bad bins
    #                 v_QC[:, t_i] = 2  # probably_good_value flag=2, or good_value flag=1

    for v_QC in vels_QC:
        v_QC[np.logical_and(diffs > 0, v_QC != 4)] = 3  # probably_bad_value
        v_QC[np.logical_and(diffs <= 0, v_QC != 4)] = 1  # probably_good_value flag=2, or good_value flag=1

    print('Velocity qc variables updated')

    d.attrs['processing_history'] = d.processing_history + " Bins where beam-averaged backscatter increases were" \
                                                           " flagged as probably_bad_value timestep by timestep."

    d.attrs['processing_history'] = d.processing_history + " The remaining bins were flagged as " \
                                                           "probably_good_value."

    #return susp_bin_list
    return


def plot_pres_compare(d: xr.Dataset, dest_dir):
    """
    For plotting ADCP pressure for ADCPs without pressure sensors
    Such ADCP files had pressure calculated from static instrument depth in L1 processing
    Requires PREXMCAT data: ADCP pressure calculated from CTD pressure
    Requires PRESPR01 data: ADCP pressure calculated from static instrument depth in L1
    Inputs:
        - d: netCDF ADCP data in xarray dataset format
    Outputs:
        None
    """

    fig = plt.figure()
    ax = fig.add_subplot(1, 1, 1)
    f1 = ax.plot(d.time.data, d.PREXMCAT.data, linewidth=1, color='r',
                 label='PREXMCAT (CTD-derived)')
    f2 = ax.plot(d.time.data, d.PRESPR01.data, linewidth=1, color='k',
                 label='PRESPR01 (static)')
    ax.set_ylim(bottom=0, top=np.ceil(np.nanmax([d.PREXMCAT.data, d.PRESPR01.data]) / 10.) * 10.)
    ax.set_xlabel('Time (UTC)')
    ax.set_ylabel('Pressure (dbar)')
    ax.legend(loc='lower left')
    ax.set_title('{}-{} {} at {} m depth: Static VS CTD-derived pressure'.format(
        d.attrs['station'], d.attrs['deployment_number'], d.attrs['serial_number'],
        d.attrs['instrument_depth']))

    # Create L2_Python_plots subfolder if not made already
    plot_dir = './{}/L2_Python_plots/'.format(dest_dir)
    if not os.path.exists(plot_dir):
        os.makedirs(plot_dir)

    fig_name = plot_dir + '{}-{}_{}_CTD_pressure_compare.png'.format(
        d.station.lower(), str(d.deployment_number), d.serial_number)
    fig.savefig(fig_name)
    plt.close()

    return os.path.abspath(fig_name)


def plot_backscatter_qc(d:xr.Dataset, dest_dir):
    """
    Calculate depths from bin distances from instrument
    Inputs:
        - d: dataset-type object created by reading in a netCDF ADCP file with the xarray package
        - bad_bin_list: an array containing the index of the first bad bin at each time step;
                        "bad bins" are designated as having negative pressure or are below ocean floor depth
        - susp_bin_list: an array containing the index of the first suspicious bin at each time step;
                         "suspicious bins" are designated as observing backscatter increases.
                         This kwarg is optional as it only applies for upwards-facing ADCPs.
    Outputs:
        None
    """

    # Calculate bin depths
    depths = pwl.calculate_depths(d)

    # Calculate average backscatter (amplitude intensity) over time for each beam
    amp_mean_b1 = np.nanmean(d.TNIHCE01.data, axis=1)
    amp_mean_b2 = np.nanmean(d.TNIHCE02.data, axis=1)
    amp_mean_b3 = np.nanmean(d.TNIHCE03.data, axis=1)
    amp_mean_b4 = np.nanmean(d.TNIHCE04.data, axis=1)

    # Check if vertical beam data present in Sentinel V file
    flag_vb = pwl.vb_flag(d)
    if d.instrumentSubtype == 'Sentinel V' and flag_vb == 0:
        amp_mean_b5 = np.nanmean(d.TNIHCE05.data, axis=1)
        # Make lists of mean amplitude and corresponding plotting colours
        amp = [amp_mean_b1, amp_mean_b2, amp_mean_b3, amp_mean_b4, amp_mean_b5]
        colours = ['b', 'g', 'c', 'm', 'y']
    else:
        amp = [amp_mean_b1, amp_mean_b2, amp_mean_b3, amp_mean_b4]
        colours = ['b', 'g', 'c', 'm']

    amp_mean_all = np.nanmean(amp, axis=0)

    # Do backscatter increase and negative pressure flagging specially for each time time-avged beam
    mean_bad_bin = 0
    mean_susp_bin = 0
    if d.orientation == 'up':
        try:
            pres_mean = np.nanmean(d.PREXMCAT.data)
        except AttributeError:
            pres_mean = np.nanmean(d.PRESPR01.data)

        for i in range(len(d.distance.data)):
            bin_pres = pres_mean - d.distance.data[i]
            if bin_pres < 0:
                mean_bad_bin = i
                break

        for i in range(2, len(amp_mean_all)):
            if amp_mean_all[i] > amp_mean_all[i-1]:
                mean_susp_bin = i
                break
    else:
        for i in range(len(d.distance.data)):
            bin_depth = d.instrument_depth + d.distance.data[i]
            if bin_depth > d.water_depth:
                mean_bad_bin = i

    # Plot flagged average backscatter (QC):
    # Plot Good, Suspicious, and Bad data separately on the same plot
    fig = plt.figure(figsize=(4, 8.5))  # figsize=(11, 8.5), (8, 8.5) for two subplots
    ax = fig.add_subplot(1, 1, 1)  # (nrows, ncols, index)
    beam_no = 1
    for dat, col in zip(amp, colours):
        if mean_bad_bin != 0:
            #Median bad bin is not zero  # plot bad_data
            f1 = ax.plot(dat[mean_bad_bin - 1:], depths[mean_bad_bin - 1:], linewidth=1, marker='o', markersize=2,
                         color='r')
            if mean_susp_bin != 0:
                # Median number of bins flagged by backscatter increases is not zero  # Plot suspicious data
                f2 = ax.plot(dat[mean_susp_bin - 1:mean_bad_bin], depths[mean_susp_bin - 1:mean_bad_bin],
                             linewidth=1, marker='o', markersize=2, color='tab:orange')
                # Plot good_data
                f3 = ax.plot(dat[:mean_susp_bin], depths[:mean_susp_bin], label='Beam {}'.format(beam_no),
                             linewidth=1, marker='o', markersize=2, color=col)
            else:
                # Zero suspicious bins (bins where backscatter increases); plot good_data limited by bad_data
                f2 = ax.plot(dat[:mean_bad_bin], depths[:mean_bad_bin], label='Beam {}'.format(beam_no), linewidth=1,
                             marker='o', markersize=2, color=col)
        else:
            # Median zero bad bins (bins where pressure is negative)
            if mean_susp_bin != 0:
                # Median number of bins flagged by backscatter increases is not zero
                f1 = ax.plot(dat[mean_susp_bin - 1:], depths[mean_susp_bin - 1:],
                             linewidth=1, marker='o', markersize=2, color='tab:orange')
                f2 = ax.plot(dat[:mean_susp_bin], depths[:mean_susp_bin], label='Beam {}'.format(beam_no),
                             linewidth=1, marker='o', markersize=2, color=col)
            else:
                # Zero bins where backscatter increases
                f1 = ax.plot(dat[:], depths[:], label='Beam {}'.format(beam_no), linewidth=1,
                             marker='o', markersize=2, color=col)
        beam_no += 1

    # Add flag plot text
    if mean_bad_bin != 0:
        x_pos = np.max(amp_mean_b1)
        y_pos = np.nanmean(depths[mean_bad_bin:])
        ax.text(x=x_pos, y=y_pos, s='Flag=4',
                horizontalalignment='right', verticalalignment='center', fontsize=10)
    if mean_susp_bin != 0:
        x_pos = np.nanmean(amp_mean_b1)
        if mean_bad_bin != 0:
            y_pos = np.nanmean(depths[mean_susp_bin - 1:mean_bad_bin])
            ax.text(x=x_pos, y=y_pos,
                    s='Flag=3', horizontalalignment='right', verticalalignment='center', fontsize=10)
        else:
            y_pos = np.nanmean(depths[mean_susp_bin - 1:])
            ax.text(x=x_pos, y=y_pos,
                    s='Flag=3', horizontalalignment='right', verticalalignment='center', fontsize=10)

    ax.set_ylim(depths[-1], depths[0])
    ax.legend(loc='lower left')
    ax.set_xlabel('Counts')
    ax.set_ylabel('Depth (m)')  # Set y axis label for this subplot only out of the 3
    ax.grid()
    ax.tick_params(axis='both', direction='in', top=True, right=True)
    ax.set_title('Mean Backscatter', fontweight='semibold')  # subplot title
    if d.orientation == 'up':
        plt.gca().invert_yaxis()

    fig.suptitle('{}-{} {} at {} m depth: L2 QC'.format(d.attrs['station'],
                                                        d.attrs['deployment_number'],
                                                        d.attrs['serial_number'],
                                                        d.attrs['instrument_depth']), fontweight='semibold')

    # Create L2_Python_plots subfolder if not already existing
    plot_dir = './{}/L2_Python_plots/'.format(dest_dir)
    if not os.path.exists(plot_dir):
        os.makedirs(plot_dir)

    fig_name = plot_dir + '{}-{}_{}_nc_L2.png'.format(
        d.station.lower(), str(d.deployment_number), d.serial_number)
    fig.savefig(fig_name)
    plt.close()

    return os.path.abspath(fig_name)


def bad_2_nan(d:xr.Dataset):
    """
    Apply flags to velocity data.
    Inputs:
        - d: netCDF ADCP file in xarray dataset format
    Outputs:
        None
    """

    print(d.LCEWAP01.data.shape)
    print(d.LCEWAP01_QC.data.shape)

    # Redo setting bad velocity data to nans based on updates from pressure or ocean floor depth analysis
    d.LCEWAP01.data[d.LCEWAP01_QC.data == 4] = np.nan
    d.LCNSAP01.data[d.LCNSAP01_QC.data == 4] = np.nan
    d.LRZAAP01.data[d.LRZAAP01_QC.data == 4] = np.nan

    flag_vb = pwl.vb_flag(d)
    if d.instrumentSubtype == 'Sentinel V' and flag_vb == 0:
        d.LRZUVP01.data[d.LRZUVP01_QC == 4] = np.nan

    d.attrs['processing_history'] = d.processing_history + " Velocity data that were flagged as bad_data were set" \
                                                           " to nans."

    # Reset velocity data_min and data_max variable attributes
    reset_vel_minmaxes(d=d)
    return


def reset_vel_minmaxes(d:xr.Dataset):
    """
    Function for re-calculating data_min and data_max variable attributes
    Inputs:
        - d: xarray object created by reading in a netCDF ADCP file with xarray.open_dataset()
    Outputs:
        None
    """

    flag_vb = pwl.vb_flag(d)
    if d.instrumentSubtype == 'Sentinel V' and flag_vb == 0:
        var_list = [d.LCEWAP01, d.LCNSAP01, d.LRZAAP01, d.LRZUVP01, d.LERRAP01, d.LCEWAP01_QC, d.LCNSAP01_QC,
                    d.LRZAAP01_QC, d.LRZUVP01_QC]
    else:
        var_list = [d.LCEWAP01, d.LCNSAP01, d.LRZAAP01, d.LERRAP01, d.LCEWAP01_QC, d.LCNSAP01_QC,
                    d.LRZAAP01_QC]

    # Reset mins and maxes
    for var in var_list:
        var.attrs['data_max'] = np.nanmax(var.data)
        var.attrs['data_min'] = np.nanmin(var.data)
    return


def get_segment_start_end_idx_depth(
        segment_starts_ends, pressure, latitude,
        datetime_pd: np.ndarray, original_instr_depth: float):
    # Assume the first segment instrument depth was already correct
    # before the mooring was displaced, so pass the original depth here

    # Create flag
    ds_is_split = True

    # Convert the user-input segment starts and ends into usable format
    if type(segment_starts_ends) == dict:
        # Determine the type of the objects in the list
        if all([type(k) == str for k in segment_starts_ends.keys()]):
            # object is a datetime in string format 'YYYYMMDD HH:MM:SS'
            segment_starts_ends = {
                pd.to_datetime(k): pd.to_datetime(v)
                for k, v in segment_starts_ends.items()
            }
            # Convert it to an index (integer type)
            idx = {}
            for k, v in segment_starts_ends.items():
                idx_k = np.where(
                    abs(datetime_pd - pd.to_datetime(k)
                        ) == min(abs(datetime_pd - pd.to_datetime(k)))
                )[0]
                print(idx_k)
                idx_v = np.where(
                    abs(datetime_pd - pd.to_datetime(v)
                        ) == min(abs(datetime_pd - pd.to_datetime(v)))
                )[0]
                idx[idx_k[0]] = idx_v[0]
            segment_start_end_idx = idx
        elif all([type(k) == int for k in segment_starts_ends.keys()]):
            segment_start_end_idx = segment_starts_ends
    elif segment_starts_ends is None:
        segment_start_end_idx = {0: len(datetime_pd) - 1}  # {0: -1}??
        ds_is_split = False
    else:
        print(
            f'Error: segment start and end items are type {type(segment_starts_ends)} and must be dict or None'
        )

    # Add 1 to the end index because python indexing is not inclusive
    for k, v in segment_start_end_idx.items():
        segment_start_end_idx[k] = v + 1

    # Get the mean instrument depth for each segment
    segment_instrument_depths = np.zeros(
        len(segment_start_end_idx), dtype='float32')

    for i, k, v in zip(range(len(segment_start_end_idx)),
                       segment_start_end_idx.keys(),
                       segment_start_end_idx.values()):
        # Height (positive up) must be converted to depth (positive down)
        # Round to 1 decimal place
        if i == 0:
            segment_instrument_depths[i] = original_instr_depth
        else:
            segment_instrument_depths[i] = np.round(np.nanmean(
                    -gsw.z_from_p(pressure[k: v], latitude)), 1)

    return segment_start_end_idx, segment_instrument_depths, ds_is_split


def make_subset_from_dataset(
        ds: xr.Dataset, start_idx: int, end_idx: int,
        instrument_depth: float, ds_is_split: bool, new_filename: str,
        recovery_lat_lon=None):

    # Add variables
    var_dict = {}
    for key in ds.data_vars.keys():
        if key == 'filename':
            var_dict[key] = ([], new_filename)
        elif key in ['latitude', 'ALATZZ01'] and recovery_lat_lon is not None:
            var_dict[key] = ([], recovery_lat_lon[0])
        elif key in ['longitude', 'ALONZZ01'] and recovery_lat_lon is not None:
            var_dict[key] = ([], recovery_lat_lon[1])
        elif 'time' in ds[key].coords:
            if 'distance' in ds[key].coords:
                var_dict[key] = (['distance', 'time'],
                                 ds[key].data[:, start_idx:end_idx])
            else:
                var_dict[key] = (['time'],
                                 ds[key].data[start_idx:end_idx])
        elif 'distance' in ds[key].coords:
            var_dict[key] = (['distance'], ds[key].data)
        else:
            var_dict[key] = ([], ds[key].data)

    dsout = xr.Dataset(
        coords={'time': ds.time.data[start_idx:end_idx],
                'distance': ds.distance.data}, data_vars=var_dict)

    # Add attributes and encoding back to the variables
    for var in dsout.keys():
        try:
            dsout[var].encoding['_FillValue'] = ds[var].encoding['_FillValue']
        except KeyError:
            pass
        for attr, attr_val in ds[var].attrs.items():
            # Recalculate data min and max
            if attr == 'data_min':
                dsout[var].attrs[attr] = np.nanmin(
                    dsout[var].data)
            elif attr == 'data_max':
                dsout[var].attrs[attr] = np.nanmax(
                    dsout[var].data)
            # Update sensor depth for each segment
            elif attr == 'sensor_depth':
                dsout[var].attrs[attr] = instrument_depth
            else:
                dsout[var].attrs[attr] = attr_val

    # Add global attributes
    for key, value in ds.attrs.items():
        dsout.attrs[key] = value

    # todo Update any attributes that are depth- and/or time-dependent
    GLOBAL_ATTRS_TO_UPDATE = [
        'instrument_depth', 'processing_history',
        'time_coverage_duration', 'time_coverage_start', 'source',
        'time_coverage_end', 'geospatial_vertical_min',
        'geospatial_vertical_max', 'date_modified',
        'geospatial_lat_min', 'geospatial_lat_max',
        'geospatial_lon_min', 'geospatial_lon_max']

    ns_to_days = 1./(60 * 60 * 24 * 1e9)

    if dsout.orientation == 'up':
        geospatial_vertical_min = dsout.instrument_depth - np.nanmax(dsout.distance.data)
        geospatial_vertical_max = dsout.instrument_depth - np.nanmin(dsout.distance.data)
    elif dsout.orientation == 'down':
        geospatial_vertical_min = dsout.instrument_depth + np.nanmin(dsout.distance.data)
        geospatial_vertical_max = dsout.instrument_depth + np.nanmax(dsout.distance.data)

    dsout.attrs['instrument_depth'] = instrument_depth
    if ds_is_split:
        dsout.attrs['processing_history'] += ' The data were segmented by pressure ' \
                                             'changes possibly due to a mooring strike.'
    # duration must be in decimal days format
    dsout.attrs['time_coverage_duration'] = float(
        dsout.time.data[-1] - dsout.time.data[0]) * ns_to_days
    # dsout.attrs['source'] = 'https://github.com/IOS-OSD-DPG/pycurrents_ADCP_processing'
    # string format
    dsout.attrs['time_coverage_start'] = dsout.DTUT8601.data[0] + ' UTC'
    dsout.attrs['time_coverage_end'] = dsout.DTUT8601.data[-1] + ' UTC'
    dsout.attrs['geospatial_vertical_min'] = geospatial_vertical_min
    dsout.attrs['geospatial_vertical_max'] = geospatial_vertical_max
    dsout.attrs['date_modified'] = datetime.now(timezone.utc).strftime(
        '%Y-%m-%d %H:%M:%S UTC')
    if recovery_lat_lon is not None:
        dsout.attrs['geospatial_lat_min'] = recovery_lat_lon[0]
        dsout.attrs['geospatial_lat_max'] = recovery_lat_lon[0]
        dsout.attrs['geospatial_lon_min'] = recovery_lat_lon[1]
        dsout.attrs['geospatial_lon_max'] = recovery_lat_lon[1]
    return dsout


def create_nc_L2(f_adcp: str, dest_dir: str, f_ctd=None,
                 segment_starts_ends=None, recovery_lat_lon=None):
    """
    Function for performing the suite of L2 processing methods on netCDF ADCP
    data.
    Inputs:
        - The name of a netCDF ADCP file
        - The name of a netCDF CTD file
          (required if ADCP file didn't have pressure sensor data)
    Outputs:
        - The name of the output netCDF ADCP file
    """

    if not os.path.exists(dest_dir):
        os.makedirs(dest_dir)

    # # Set name for new output netCDF
    # nc_out_name = os.path.basename(f_adcp).replace('L1', 'L2')
    # print(nc_out_name)
    # if not dest_dir.endswith('/') or not dest_dir.endswith('\\'):
    #     out_absolute_name = os.path.abspath(dest_dir + '/' + nc_out_name)
    # else:
    #     out_absolute_name = os.path.abspath(dest_dir + nc_out_name)

    # Open netCDF ADCP file
    nc_adcp = xr.open_dataset(f_adcp)

    # # Change value of filename variable to include "L2" instead of "L1"
    # nc_adcp = nc_adcp.assign(filename=((), nc_out_name[:-3]))

    # Produce pre-processing plots
    plot_diagn = pwl.plots_diagnostic(nc_adcp, dest_dir)

    flag_static_pres = 0
    if nc_adcp.orientation == 'up':
        # Identify bins through time series where their pressure is negative
        if np.nanmin(nc_adcp.PRESPR01.data) == np.nanmax(nc_adcp.PRESPR01.data):
            flag_static_pres += 1
            warnings.warn(
                'Pressure was calculated from static instrument depth in L1',
                UserWarning)

        if f_ctd is not None:
            nc_sbe = xr.open_dataset(f_ctd)

            # Calculate ADCP pressure from CTD pressure
            nc_adcp = add_pressure_ctd(nc_adcp=nc_adcp, nc_ctd=nc_sbe)

            # Plot static and CTD-derived pressures
            plot_pres_comp = plot_pres_compare(nc_adcp, dest_dir)

            # Flag bad bins by negative pressure values
            flag_by_pres(d=nc_adcp, use_prexmcat=True)
        else:
            # Flag bad bins by negative pressure values
            flag_by_pres(d=nc_adcp)

        # Identify bins through time series where their backscatter
        # increases, get list of their indices
        flag_by_backsc(d=nc_adcp)

        # Make QC plots showing time-averaged negative pressure and
        # backscatter increases
        plot_backsc = plot_backscatter_qc(d=nc_adcp, dest_dir=dest_dir)
    else:
        # orientation == 'down'
        if np.nanmin(nc_adcp.PRESPR01.data) == np.nanmax(nc_adcp.PRESPR01.data):
            flag_static_pres += 1
            warnings.warn(
                'Pressure was calculated from static instrument depth in L1',
                UserWarning)

        if f_ctd is not None:
            nc_sbe = xr.open_dataset(f_ctd)

            # Calculate ADCP pressure from CTD pressure
            nc_adcp = add_pressure_ctd(nc_adcp=nc_adcp, nc_ctd=nc_sbe)

            # Plot static and CTD-derived pressures
            plot_pres_comp = plot_pres_compare(nc_adcp, dest_dir)

            # Flag bad bins by negative pressure values
            flag_by_pres(d=nc_adcp, use_prexmcat=True)

        # Identify bins through time series that are below the depth
        # of the ocean floor
        flag_below_seafloor(d=nc_adcp)

        # Make QC plots showing time-averaged flagged bins that are below
        # ocean floor depth
        plot_backsc = plot_backscatter_qc(d=nc_adcp, dest_dir=dest_dir)

    # Set bad velocity data to nans
    bad_2_nan(d=nc_adcp)

    # Add segmentation by pressure changes
    # User inputs indices or datetimes
    # returns a dictionary of the start and end indices of format {start: end}
    # and a numpy array of depths with length equal to the dictionary
    segment_st_en_idx, segment_instr_depths, ds_is_split = get_segment_start_end_idx_depth(
        segment_starts_ends, nc_adcp.PRESPR01.data, nc_adcp.latitude,
        nc_adcp.time.data, nc_adcp.instrument_depth
    )
    print(segment_instr_depths)
    # Initialize list to hold the file names of all netcdf files to be output
    segment_filenames = []

    for st_idx, en_idx, i in zip(
            segment_st_en_idx.keys(), segment_st_en_idx.values(),
            range(len(segment_instr_depths))
    ):
        # Generate as many file names as there are segments of data
        # where the segments were determined from pressure changes
        # based on the start and end times of the segments and their depths
        # only use the "date" part of the datetime
        # format the depth to 4 string characters by adding zeros if necessary

        # Need to subtract 1 from en_idx because +1 is added in
        # get_user_segment_start_end_idx_depth() for inclusive ranges
        # but ranges are not called here
        out_segment_name = '{}_{}_{}_{}m.adcp.L2.nc'.format(
            nc_adcp.station.lower(),
            nc_adcp.DTUT8601.data[st_idx][:10].replace('-', ''),
            nc_adcp.DTUT8601.data[en_idx - 1][:10].replace('-', ''),
            f'000{str(int(np.round(segment_instr_depths[i], 0)))}'[-4:])

        absolute_segment_name = os.path.join(dest_dir, out_segment_name)

        segment_filenames.append(absolute_segment_name)

        # split the dataset by creating subsets from the original
        if i < len(segment_instr_depths) - 1:
            ds_segment = make_subset_from_dataset(
                nc_adcp, st_idx, en_idx, segment_instr_depths[i],
                ds_is_split, out_segment_name)
        elif i == len(segment_instr_depths) - 1:
            ds_segment = make_subset_from_dataset(
                nc_adcp, st_idx, en_idx, segment_instr_depths[i],
                ds_is_split, out_segment_name, recovery_lat_lon)

        # Make plot of pressure to show change if dataset is split
        if len(segment_instr_depths) > 1:
            segment_pres_plot_name = pwl.plot_adcp_pressure(ds_segment, dest_dir)

        # Export the dataset object as a new netCDF file
        ds_segment.to_netcdf(absolute_segment_name, mode='w', format='NETCDF4')
        print(f'Exported L2 netCDF file {out_segment_name}')

        ds_segment.close()

    files_to_return = [*segment_filenames, plot_diagn, plot_backsc]
    if flag_static_pres == 1:
        files_to_return.append(plot_pres_comp)
    elif len(segment_instr_depths) > 1:
        files_to_return.append(segment_pres_plot_name)

    return files_to_return


def example_L2_1():
    # Sample L1 netCDF ADCP file
    f_adcp = './newnc/a1_20050503_20050504_0221m.adcp.L1.nc'
    dest_dir = 'dest_dir'

    out_files = create_nc_L2(f_adcp, dest_dir)

    return out_files


def example_L2_2():
    # Sample L1 netCDF ADCP file
    f_adcp = './newnc/e01_20120613_20130705_0091m.adcp.L1.nc'
    # netCDF CTD file from same deployment
    f_ctd = './sample_data/e01_20120613_20130705_0093m.ctd.nc'
    dest_dir = 'dest_dir'

    out_files = create_nc_L2(f_adcp, dest_dir, f_ctd)

    return out_files
