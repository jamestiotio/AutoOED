import tkinter as tk
from tkinter import ttk, scrolledtext
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
from matplotlib.ticker import MaxNLocator
from matplotlib.backend_bases import MouseButton


import os
import yaml
import numpy as np
from multiprocessing import Lock, Process
from problems.common import build_problem
from problems.utils import import_module_from_path
from system.agent import DataAgent, ProblemAgent
from system.utils import process_config, load_config, get_available_algorithms, get_available_problems, find_closest_point, check_pareto
from system.gui.radar import radar_factory
from system.gui.excel import Excel
from system.gui.utils import *


class GUI:
    '''
    Interactive local tkinter-based GUI
    '''
    def __init__(self):
        '''
        GUI initialization
        '''
        # GUI root initialization
        self.root = tk.Tk()
        self.root.title('MOBO')
        self.root.protocol("WM_DELETE_WINDOW", self._quit)
        grid_configure(self.root, [0, 1], [0], row_weights=[1, 20]) # configure for resolution change
        screen_width = self.root.winfo_screenwidth()
        max_width = 1280
        width = 0.8 * screen_width
        if width > max_width: width = max_width
        height = 0.5 * width
        self.root.geometry(f'{int(width)}x{int(height)}')

        # predefined GUI parameters
        self.refresh_rate = 100 # ms
        self.result_dir = os.path.abspath('result') # initial result directory

        # agent
        self.agent_data = None
        self.agent_problem = ProblemAgent()

        # running processes
        self.processes = []
        self.process_id = 0
        self.lock = Lock()

        # config related
        self.config = None
        self.config_raw = None
        self.config_id = -1

        # event widgets
        self.button_optimize = None
        self.button_stop = None
        self.button_input = None
        self.scrtext_config = None
        self.scrtext_log = None

        # data to be plotted
        self.scatter_x = None
        self.scatter_y = None
        self.scatter_y_pareto = None
        self.annotate = None
        self.line_x = None
        self.fill_x = None
        self.line_hv = None
        self.line_error = None

        # status variables
        self.n_init_sample = None
        self.n_curr_sample = None
        self.curr_iter = tk.IntVar()
        self.max_iter = 0

        # GUI modules initialization
        self._init_menu()
        self._init_widgets()

    def _init_menu(self):
        '''
        Menu initialization
        '''
        # top-level menu
        self.menu = tk.Menu(master=self.root, relief='raised')
        self.root.config(menu=self.menu)

        # sub-level menu
        self.menu_file = tk.Menu(master=self.menu, tearoff=0)
        self.menu.add_cascade(label='File', menu=self.menu_file)
        self.menu_config = tk.Menu(master=self.menu, tearoff=0)
        self.menu.add_cascade(label='Config', menu=self.menu_config)
        self.menu_problem = tk.Menu(master=self.menu, tearoff=0)
        self.menu.add_cascade(label='Problem', menu=self.menu_problem)
        self.menu_log = tk.Menu(master=self.menu, tearoff=0)
        self.menu.add_cascade(label='Log', menu=self.menu_log)

        # init sub-level menu
        self._init_file_menu()
        self._init_config_menu()
        self._init_problem_menu()
        self._init_log_menu()

    def _init_file_menu(self):
        '''
        File menu initialization
        '''
        self.menu_file.add_command(label='Save in...')

        def gui_change_saving_path():
            '''
            Change data saving path
            '''
            dirname = tk.filedialog.askdirectory(parent=self.root)
            if not isinstance(dirname, str) or dirname == '': return
            self.result_dir = dirname

        # link menu command
        self.menu_file.entryconfig(0, command=gui_change_saving_path)

    def _init_config_menu(self):
        '''
        Config menu initialization
        '''
        self.menu_config.add_command(label='Load')
        self.menu_config.add_command(label='Create')
        self.menu_config.add_command(label='Change')

        def gui_load_config():
            '''
            Load config from file
            '''
            filename = tk.filedialog.askopenfilename(parent=self.root)
            if not isinstance(filename, str) or filename == '': return

            try:
                config = load_config(filename)
            except:
                tk.messagebox.showinfo('Error', 'Invalid yaml file', parent=self.root)
                self.button_optimize.configure(state=tk.DISABLED)
                return
                
            self._set_config(config)

        def gui_build_config_window(change=False):
            '''
            Build config GUI
            '''
            # displayed name of each property
            name_map = {
                'general': {
                    'n_init_sample': 'Number of initial samples',
                    'batch_size': 'Batch size',
                    'n_iter': 'Number of optimization iterations',
                    'n_process': 'Number of optimization processes',
                },
                'problem': {
                    'name': 'Name of problem',
                    'n_var': 'Number of design variables',
                    'n_obj': 'Number of objectives',
                    'var_lb': 'Lower bound',
                    'var_ub': 'Upper bound',
                    'var_name': 'Name of design variables',
                    'obj_name': 'Name of objectives',
                    'ref_point': 'Reference point',
                },
                'algorithm': {
                    'name': 'Name of algorithm'
                },
            }

            # arrange widgets as a dict with same structure as config
            widget_map = {
                'general': {}, 
                'problem': {}, 
                'algorithm': {},
            }

            window = tk.Toplevel(master=self.root)
            window.title('Create Configurations')
            window.configure(bg='white')
            window.resizable(False, False)

            # parameter section
            frame_param = tk.Frame(master=window, bg='white')
            frame_param.grid(row=0, column=0)

            # general subsection
            frame_general = create_labeled_frame(master=frame_param, row=0, column=0, text='General')
            widget_map['general']['n_init_sample'] = create_labeled_entry(
                master=frame_general, row=0, column=0, text=name_map['general']['n_init_sample'], class_type=IntEntry, required=True, 
                valid_check=lambda x: x > 0, error_msg='number of initial samples must be positive', changeable=False)
            widget_map['general']['batch_size'] = create_labeled_entry(
                master=frame_general, row=1, column=0, text=name_map['general']['batch_size'], class_type=IntEntry, required=True, 
                valid_check=lambda x: x > 0, error_msg='number of batch size must be positive')
            widget_map['general']['n_iter'] = create_labeled_entry(
                master=frame_general, row=2, column=0, text=name_map['general']['n_iter'], class_type=IntEntry, required=True, 
                valid_check=lambda x: x > 0, error_msg='number of optimization iteration must be positive')
            widget_map['general']['n_process'] = create_labeled_entry(
                master=frame_general, row=3, column=0, text=name_map['general']['n_process'], class_type=IntEntry, default=1, 
                valid_check=lambda x: x > 0, error_msg='number of processes to use must be positive')

            # problem subsection
            frame_problem = create_labeled_frame(master=frame_param, row=0, column=1, text='Problem')
            widget_map['problem']['name'] = create_labeled_combobox(
                master=frame_problem, row=0, column=0, text=name_map['problem']['name'], values=get_available_problems(), required=True, 
                valid_check=lambda x: x in get_available_problems(), error_msg="problem doesn't exist", changeable=False)
            widget_map['problem']['n_var'] = create_labeled_entry(
                master=frame_problem, row=1, column=0, text=name_map['problem']['n_var'], class_type=IntEntry, 
                valid_check=lambda x: x > 0, error_msg='number of design variables must be positive', changeable=False)
            widget_map['problem']['n_obj'] = create_labeled_entry(
                master=frame_problem, row=2, column=0, text=name_map['problem']['n_obj'], class_type=IntEntry, 
                valid_check=lambda x: x > 1, error_msg='number of objectives must be greater than 1', changeable=False)
            widget_map['problem']['var_lb'] = create_labeled_entry(
                master=frame_problem, row=3, column=0, text=name_map['problem']['var_lb'], class_type=FloatListEntry, width=10, 
                valid_check=lambda x: len(x) in [1, widget_map['problem']['n_var'].get()], error_msg='size of bound mismatches number of design variables') # TODO: default?
            widget_map['problem']['var_ub'] = create_labeled_entry(
                master=frame_problem, row=4, column=0, text=name_map['problem']['var_ub'], class_type=FloatListEntry, width=10, 
                valid_check=lambda x: len(x) in [1, widget_map['problem']['n_var'].get()], error_msg='size of bound mismatches number of design variables') # TODO: default?
            widget_map['problem']['var_name'] = create_labeled_entry(
                master=frame_problem, row=5, column=0, text=name_map['problem']['var_name'], class_type=StringListEntry, width=10, 
                valid_check=lambda x: len(x) == widget_map['problem']['n_var'].get(), error_msg='number of names mismatches number of design variables', changeable=False) # TODO: default?
            widget_map['problem']['obj_name'] = create_labeled_entry(
                master=frame_problem, row=6, column=0, text=name_map['problem']['obj_name'], class_type=StringListEntry, width=10, 
                valid_check=lambda x: len(x) == widget_map['problem']['n_obj'].get(), error_msg='number of names mismatches number of objectives', changeable=False) # TODO: default?
            widget_map['problem']['ref_point'] = create_labeled_entry(
                master=frame_problem, row=7, column=0, text=name_map['problem']['ref_point'], class_type=FloatListEntry, width=10, 
                valid_check=lambda x: len(x) == widget_map['problem']['n_obj'].get(), error_msg='dimension of reference point mismatches number of objectives', changeable=False) # TODO: changeable

            # algorithm subsection
            frame_algorithm = create_labeled_frame(master=frame_param, row=0, column=2, text='Algorithm')
            widget_map['algorithm']['name'] = create_labeled_combobox(
                master=frame_algorithm, row=0, column=0, text=name_map['algorithm']['name'], values=get_available_algorithms(), required=True, 
                valid_check=lambda x: x in get_available_algorithms(), error_msg="algorithm doesn't exist")

            def load_curr_config():
                '''
                Set values of widgets as current configuration values
                '''
                for cfg_type, val_map in widget_map.items():
                    for cfg_name, widget in val_map.items():
                        widget.set(self.config[cfg_type][cfg_name])
                        if not widget.changeable:
                            widget.disable()

            def gui_save_config():
                '''
                Save specified configuration values
                '''
                config = {
                    'general': {}, 
                    'problem': {}, 
                    'algorithm': {},
                }

                # set config values from widgets
                for cfg_type, val_map in widget_map.items():
                    for cfg_name, widget in val_map.items():
                        try:
                            config[cfg_type][cfg_name] = widget.get()
                        except:
                            error_msg = widget.get_error_msg()
                            error_msg = '' if error_msg is None else ': ' + error_msg
                            tk.messagebox.showinfo('Error', f'Invalid value for "{name_map[cfg_type][cfg_name]}"' + error_msg, parent=window)
                            return

                try:
                    config = process_config(config)
                except:
                    tk.messagebox.showinfo('Error', 'Invalid configurations', parent=window)
                    return

                self._set_config(config, window)
                window.destroy()

            # action section
            frame_action = tk.Frame(master=window, bg='white')
            frame_action.grid(row=1, column=0, columnspan=3)
            create_button(master=frame_action, row=0, column=0, text='Save', command=gui_save_config)
            create_button(master=frame_action, row=0, column=1, text='Cancel', command=window.destroy)

            # load current config values to entry if not first time setting config
            if change:
                load_curr_config()

        def gui_create_config():
            '''
            Create config from GUI
            '''
            gui_build_config_window(change=False)

        def gui_change_config():
            '''
            Change config from GUI
            '''
            gui_build_config_window(change=True)

        # link menu command
        self.menu_config.entryconfig(0, command=gui_load_config)
        self.menu_config.entryconfig(1, command=gui_create_config)
        self.menu_config.entryconfig(2, command=gui_change_config, state=tk.DISABLED)

    def _init_problem_menu(self):
        '''
        Problem menu initialization
        '''
        self.menu_problem.add_command(label='Create') # TODO
        self.menu_problem.add_command(label='Manage') # TODO

        def gui_create_problem():
            '''
            Create problem from GUI
            '''
            # displayed name of each property
            name_map = {
                'name': 'Name',
                'n_var': 'Number of design variables',
                'n_obj': 'Number of objectives',
                'n_constr': 'Number of constraints',
                'performance_eval': 'Performance evaluation script',
                'constraint_eval': 'Constraint evaluation script',
                'var_name': 'Names',
                'obj_name': 'Names',
                'var_lb': 'Lower bound',
                'var_ub': 'Upper bound',
                'obj_lb': 'Lower bound',
                'obj_ub': 'Upper bound',
            }

            # problem config, structured as a dict
            problem_cfg = {}

            window_0 = tk.Toplevel(master=self.root)
            window_0.title('Create Problem')
            window_0.configure(bg='white')
            window_0.resizable(False, False)

            # problem section
            frame_problem = create_labeled_frame(master=window_0, row=0, column=0, text='Problem')
            widget_map = {}
            widget_map['name'] = create_labeled_entry(
                master=frame_problem, row=0, column=0, text=name_map['name'], class_type=StringEntry, width=15, required=True, 
                valid_check=lambda x: x not in get_available_problems(), error_msg='problem already exists')
            widget_map['n_var'] = create_labeled_entry(
                master=frame_problem, row=1, column=0, text=name_map['n_var'], class_type=IntEntry, 
                valid_check=lambda x: x > 0, error_msg='number of design variables must be positive')
            widget_map['n_obj'] = create_labeled_entry(
                master=frame_problem, row=2, column=0, text=name_map['n_obj'], class_type=IntEntry, 
                valid_check=lambda x: x > 1, error_msg='number of objectives must be greater than 1')
            widget_map['n_constr'] = create_labeled_entry(
                master=frame_problem, row=3, column=0, text=name_map['n_constr'], class_type=IntEntry, default=0, 
                valid_check=lambda x: x >= 0, error_msg='number of constraints must be positive')

            def gui_set_performance_script():
                '''
                Set path of performance evaluation script
                '''
                filename = tk.filedialog.askopenfilename(parent=window_0)
                if not isinstance(filename, str) or filename == '': return
                widget_map['performance_eval'].set(filename)

            def performance_script_valid_check(path):
                '''
                Check validity of performance script located at path
                '''
                if path is None:
                    return False
                try:
                    module = import_module_from_path('eval_check', path)
                    module.evaluate_performance
                except:
                    return False
                return True

            frame_performance_script = create_frame(master=frame_problem, row=4, column=0, padx=0)
            create_label(master=frame_performance_script, row=0, column=0, text=name_map['performance_eval'] + ' (*): ', columnspan=2)
            create_button(master=frame_performance_script, row=1, column=0, text='Browse', command=gui_set_performance_script, pady=0)
            widget_map['performance_eval'] = create_entry(
                master=frame_performance_script, row=1, column=1, class_type=StringEntry, width=30, required=True, 
                valid_check=performance_script_valid_check, error_msg="performance evaluation script doesn't exist or no evaluate_performance() function inside", pady=0)

            def gui_set_constraint_script():
                '''
                Set path of constraint evaluation script
                '''
                filename = tk.filedialog.askopenfilename(parent=window_0)
                if not isinstance(filename, str) or filename == '': return
                widget_map['constraint_eval'].set(filename)

            def constraint_script_valid_check(path):
                '''
                Check validity of constraint script located at path
                '''
                if path is None:
                    return False
                try:
                    module = import_module_from_path('eval_check', path)
                    module.evaluate_constraint
                except:
                    return False
                return True

            frame_constraint_script = create_frame(master=frame_problem, row=5, column=0, padx=0)
            create_label(master=frame_constraint_script, row=0, column=0, text=name_map['constraint_eval'] + ': ', columnspan=2)
            create_button(master=frame_constraint_script, row=1, column=0, text='Browse', command=gui_set_constraint_script, pady=0)
            widget_map['constraint_eval'] = create_entry(
                master=frame_constraint_script, row=1, column=1, class_type=StringEntry, width=30, 
                valid_check=constraint_script_valid_check, error_msg="constraint evaluation script doesn't exist or no evaluate_constraint() function inside", pady=0)

            def save_entry_values(entry_map, config):
                '''
                Save values of entries to config dict
                '''
                for name, widget in entry_map.items():
                    try:
                        config[name] = widget.get()
                    except:
                        error_msg = widget.get_error_msg()
                        error_msg = '' if error_msg is None else ': ' + error_msg
                        tk.messagebox.showinfo('Error', f'Invalid value for "{name_map[name]}"' + error_msg, parent=window_0)
                        raise Exception()

            def gui_set_design_space():
                '''
                Set design space parameters
                '''
                # save current entry values
                try:
                    save_entry_values(widget_map, problem_cfg)
                except:
                    return
                window_0.destroy()

                window_1 = tk.Toplevel(master=self.root)
                window_1.title('Create Problem')
                window_1.configure(bg='white')
                window_1.resizable(False, False)

                # design space section
                frame_design = create_labeled_frame(master=window_1, row=0, column=0, text='Design Space')
                create_label(master=frame_design, row=0, column=0, text='Enter the properties for design variables:')
                n_var = problem_cfg['n_var'] if problem_cfg['n_var'] is not None else 1
                excel_design = Excel(master=frame_design, rows=n_var, columns=3, width=15,
                    title=[name_map['var_name'], name_map['var_lb'], name_map['var_ub']], dtype=[str, float, float], default=[None, 0, 1])
                excel_design.grid(row=1, column=0)
                excel_design.set_column(0, [f'x{i + 1}' for i in range(n_var)])

                def save_design_excel_values(excel, config):
                    '''
                    Save values of design properties to config dict
                    '''
                    for key, column in zip(['var_name', 'var_lb', 'var_ub'], [0, 1, 2]):
                        try:
                            config[key] = excel.get_column(column)
                        except:
                            tk.messagebox.showinfo('Error', f'Invalid value for "{name_map[key]}"', parent=window_1)
                            raise Exception()

                def gui_set_performance_space():
                    '''
                    Set performance space parameters
                    '''
                    # save current entry values
                    try:
                        save_design_excel_values(excel_design, problem_cfg)
                    except:
                        return
                    window_1.destroy()

                    window_2 = tk.Toplevel(master=self.root)
                    window_2.title('Create Problem')
                    window_2.configure(bg='white')
                    window_2.resizable(False, False)

                    # performance space section
                    frame_performance = create_labeled_frame(master=window_2, row=0, column=0, text='Performance Space')
                    create_label(master=frame_performance, row=0, column=0, text='Enter the properties for objectives:')
                    n_obj = problem_cfg['n_obj'] if problem_cfg['n_obj'] is not None else 1
                    excel_performance = Excel(master=frame_performance, rows=n_obj, columns=3, width=15,
                        title=[name_map['obj_name'], name_map['obj_lb'], name_map['obj_ub']], dtype=[str, float, float])
                    excel_performance.grid(row=1, column=0)
                    excel_performance.set_column(0, [f'f{i + 1}' for i in range(n_obj)])

                    def save_performance_excel_values(excel, config):
                        '''
                        Save values of performance properties to config dict
                        '''
                        for key, column in zip(['obj_name', 'obj_lb', 'obj_ub'], [0, 1, 2]):
                            try:
                                config[key] = excel.get_column(column)
                            except:
                                tk.messagebox.showinfo('Error', f'Invalid value for "{name_map[key]}"', parent=window_2)
                                raise Exception()

                    def gui_finish_create_problem():
                        '''
                        Finish creating problem
                        '''
                        # save current entry values
                        try:
                            save_performance_excel_values(excel_performance, problem_cfg)
                        except:
                            return
                        window_2.destroy()

                        self.agent_problem.save_problem(problem_cfg)

                    # action section
                    frame_action = tk.Frame(master=window_2, bg='white')
                    frame_action.grid(row=1, column=0)
                    create_button(frame_action, 0, 0, 'Finish', gui_finish_create_problem)
                    create_button(frame_action, 0, 1, 'Cancel', window_2.destroy)

                # action section
                frame_action = tk.Frame(master=window_1, bg='white')
                frame_action.grid(row=1, column=0)
                create_button(frame_action, 0, 0, 'Continue', gui_set_performance_space)
                create_button(frame_action, 0, 1, 'Cancel', window_1.destroy)

            # action section
            frame_action = tk.Frame(master=window_0, bg='white')
            frame_action.grid(row=1, column=0)
            create_button(frame_action, 0, 0, 'Continue', gui_set_design_space)
            create_button(frame_action, 0, 1, 'Cancel', window_0.destroy)

        def gui_manage_problem():
            '''
            Manage created problems (TODO)
            '''
            pass

        self.menu_problem.entryconfig(0, command=gui_create_problem)
        self.menu_problem.entryconfig(1, command=gui_manage_problem)

    def _init_log_menu(self):
        '''
        Log menu initialization
        '''
        self.menu_log.add_command(label='Clear')

        def gui_log_clear():
            '''
            Clear texts in GUI log
            '''
            self.scrtext_log.configure(state=tk.NORMAL)
            self.scrtext_log.delete('1.0', tk.END)
            self.scrtext_log.configure(state=tk.DISABLED)

        # link menu command
        self.menu_log.entryconfig(0, command=gui_log_clear)
        
    def _init_widgets(self):
        '''
        Widgets initialization
        '''
        self._init_figure_widgets()
        self._init_control_widgets()
        self._init_display_widgets()

    def _init_figure_widgets(self):
        '''
        Figure widgets initialization (visualization, statistics)
        '''
        frame_figure = tk.Frame(master=self.root)
        frame_figure.grid(row=0, column=0, rowspan=2, sticky='NSEW')
        grid_configure(frame_figure, [0], [0])

        # configure tab widgets
        nb = ttk.Notebook(master=frame_figure)
        nb.grid(row=0, column=0, sticky='NSEW')
        frame_viz = tk.Frame(master=nb)
        frame_stat = tk.Frame(master=nb)
        grid_configure(frame_viz, [0], [0])
        grid_configure(frame_stat, [0], [0])
        nb.add(child=frame_viz, text='Visualization')
        nb.add(child=frame_stat, text='Statistics')

        # configure slider widget
        frame_slider = tk.Frame(master=frame_figure)
        frame_slider.grid(row=1, column=0, pady=5, sticky='EW')
        grid_configure(frame_slider, [0], [1])
        
        label_iter = tk.Label(master=frame_slider, text='Iteration:')
        label_iter.grid(row=0, column=0, sticky='EW')
        self.scale_iter = tk.Scale(master=frame_slider, orient=tk.HORIZONTAL, variable=self.curr_iter, from_=0, to=0)
        self.scale_iter.grid(row=0, column=1, sticky='EW')

        # figure placeholder in GUI (NOTE: only 2-dim performance space is supported)
        self.fig1 = plt.figure(figsize=(10, 5))
        self.gs1 = GridSpec(1, 2, figure=self.fig1, width_ratios=[3, 2])
        self.fig2 = plt.figure(figsize=(10, 5))

        # performance space figure
        self.ax11 = self.fig1.add_subplot(self.gs1[0])
        self.ax11.set_title('Performance Space')

        # design space figure
        n_var_init = 5
        self.theta = radar_factory(n_var_init)
        self.ax12 = self.fig1.add_subplot(self.gs1[1], projection='radar')
        self.ax12.set_xticks(self.theta)
        self.ax12.set_varlabels([f'x{i + 1}' for i in range(n_var_init)])
        self.ax12.set_yticklabels([])
        self.ax12.set_title('Design Space', position=(0.5, 1.1))

        # hypervolume curve figure
        self.ax21 = self.fig2.add_subplot(121)
        self.ax21.set_title('Hypervolume')
        self.ax21.set_xlabel('Evaluations')
        self.ax21.set_ylabel('Hypervolume')
        self.ax21.xaxis.set_major_locator(MaxNLocator(integer=True))

        # model prediction error figure
        self.ax22 = self.fig2.add_subplot(122)
        self.ax22.set_title('Model Prediction Error')
        self.ax22.set_xlabel('Evaluations')
        self.ax22.set_ylabel('Averaged Relative Error (%)')
        self.ax22.xaxis.set_major_locator(MaxNLocator(integer=True))

        # connect matplotlib figure with tkinter GUI
        embed_figure(self.fig1, frame_viz)
        embed_figure(self.fig2, frame_stat)

        def gui_redraw_viz(val):
            '''
            Redraw design and performance space when slider changes
            '''
            # get current iteration from slider value
            curr_iter = int(val)

            # clear design space
            self._clear_design_space()

            # replot performance space
            self._redraw_performance_space(curr_iter)

        self.scale_iter.configure(command=gui_redraw_viz)

    def _init_control_widgets(self):
        '''
        Control widgets initialization (optimize, stop, user input, show history)
        '''
        # control overall frame
        frame_control = tk.Frame(master=self.root)
        frame_control.grid(row=0, column=1, sticky='NSEW')

        # optimization command
        self.button_optimize = tk.Button(master=frame_control, text="Optimize", state=tk.DISABLED)
        self.button_optimize.grid(row=0, column=0, padx=5, pady=20, sticky='NSEW')

        # stop optimization command
        self.button_stop = tk.Button(master=frame_control, text='Stop', state=tk.DISABLED)
        self.button_stop.grid(row=0, column=1, padx=5, pady=20, sticky='NSEW')

        # get design variables from user input
        self.button_input = tk.Button(master=frame_control, text='User Input', state=tk.DISABLED)
        self.button_input.grid(row=1, column=0, columnspan=2, padx=5, pady=5, sticky='NSEW')

        def gui_optimize():
            '''
            Execute optimization
            '''
            self.menu_config.entryconfig(0, state=tk.DISABLED)
            self.menu_config.entryconfig(2, state=tk.DISABLED)
            self.button_stop.configure(state=tk.NORMAL)
            worker = Process(target=self.agent_data.optimize, args=(self.config, self.config_id))
            self._start_worker(worker)

        def gui_stop_optimize():
            '''
            Stop optimization
            '''
            with self.lock:
                for p in self.processes:
                    pid, worker = p
                    if worker.is_alive():
                        worker.terminate()
                        self._log(f'worker {pid} interrupted')
                self.processes = []
            self.button_stop.configure(state=tk.DISABLED)

        def gui_user_input():
            '''
            Getting design variables from user input
            '''
            window = tk.Toplevel(master=self.root)
            window.title('User Input')
            window.configure(bg='white')

            # description label
            label_x = tk.Label(master=window, bg='white', text='Design variable values (seperated by ","):')
            label_x.grid(row=0, column=0, padx=10, pady=10, sticky='W')

            # design variable entry
            entry_x = tk.Entry(master=window, bg='white', width=50)
            entry_x.grid(row=1, column=0, padx=10, sticky='EW')
            entry_x = FloatListEntry(widget=entry_x, valid_check=lambda x: len(x) == self.config['problem']['n_var'])

            # ask before evaluation checkbox
            ask_var = tk.IntVar()
            checkbutton_ask = tk.Checkbutton(master=window, bg='white', text='Ask before evaluation', variable=ask_var)
            checkbutton_ask.grid(row=2, column=0, padx=10, pady=10)

            # add input design variables
            button_add = tk.Button(master=window, text='Add')
            button_add.grid(row=3, column=0, ipadx=40, padx=10, pady=10)

            def gui_add_user_input():
                '''
                Predict performance of user inputted design variables, optionally do real evaluation and add to database
                '''
                # TODO: add batch input support
                try:
                    X_next = np.atleast_2d(entry_x.get())
                except:
                    tk.messagebox.showinfo('Error', 'Invalid design values', parent=window)
                    return

                ask = ask_var.get() == 1
                window.destroy()

                Y_expected, Y_uncertainty = self.agent_data.predict(self.config, X_next)

                if ask:
                    window2 = tk.Toplevel(master=self.root)
                    window2.title('Prediction Completed')
                    window2.configure(bg='white')

                    # Y_expected description
                    label_y_mean = tk.Label(master=window2, bg='white', text=f'Y_expected: ({",".join([str(y) for y in Y_expected.squeeze()])})')
                    label_y_mean.grid(row=0, column=0, columnspan=2, padx=10, pady=10, sticky='W')

                    # Y_uncertainty description
                    label_y_std = tk.Label(master=window2, bg='white', text=f'Y_uncertainty: ({",".join([str(y) for y in Y_uncertainty.squeeze()])})')
                    label_y_std.grid(row=1, column=0, columnspan=2, padx=10, pady=10, sticky='W')

                    # evaluate button
                    button_eval = tk.Button(master=window2, text='Evaluate')
                    button_eval.grid(row=2, column=0, ipadx=30, padx=10, pady=10)

                    # cancel button
                    button_cancel = tk.Button(master=window2, text='Cancel')
                    button_cancel.grid(row=2, column=1, ipadx=30, padx=10, pady=10)

                    def eval_user_input():
                        worker = Process(target=self.agent_data.update, args=(self.config, X_next, Y_expected, Y_uncertainty, self.config_id))
                        self._start_worker(worker)
                        window2.destroy()

                    button_eval.configure(command=eval_user_input)
                    button_cancel.configure(command=window2.destroy)
                else:
                    worker = Process(target=self.agent_data.update, args=(self.config, X_next, Y_expected, Y_uncertainty, self.config_id))
                    self._start_worker(worker)

            button_add.configure(command=gui_add_user_input)

        # link to commands
        self.button_optimize.configure(command=gui_optimize)
        self.button_stop.configure(command=gui_stop_optimize)
        self.button_input.configure(command=gui_user_input)

    def _init_display_widgets(self):
        '''
        Display widgets initialization (config, log)
        '''
        # configure tab widgets
        nb = ttk.Notebook(master=self.root)
        nb.grid(row=1, column=1, sticky='NSEW')
        frame_config = tk.Frame(master=nb)
        frame_log = tk.Frame(master=nb)
        nb.add(child=frame_config, text='Config')
        nb.add(child=frame_log, text='Log')

        # configure for resolution change
        grid_configure(frame_config, [0], [0])
        grid_configure(frame_log, [0], [0])

        # config display
        self.scrtext_config = scrolledtext.ScrolledText(master=frame_config, width=10, height=10, state=tk.DISABLED)
        self.scrtext_config.grid(row=0, column=0, sticky='NSEW')

        # log display
        self.scrtext_log = scrolledtext.ScrolledText(master=frame_log, width=10, height=10, state=tk.DISABLED)
        self.scrtext_log.grid(row=0, column=0, sticky='NSEW')

    def _save_config(self, config):
        '''
        Save configurations to file
        '''
        self.config_id += 1
        with open(os.path.join(self.result_dir, 'config', f'config_{self.config_id}.yml'), 'w') as fp:
            yaml.dump(config, fp, default_flow_style=False, sort_keys=False)

    def _set_config(self, config, window=None):
        '''
        Setting configurations
        '''
        # update raw config (config will be processed and changed later in build_problem())
        self.config_raw = config.copy()

        # set parent window for displaying potential error messagebox
        if window is None: window = self.root

        if self.config is None: # first time setting config
            # check if result_dir folder exists
            if os.path.exists(self.result_dir) and os.listdir(self.result_dir) != []:
                tk.messagebox.showinfo('Error', f'Result folder {self.result_dir} is not empty, please change another folder for saving results by clicking: File -> Save in...', parent=window)
                return

            os.makedirs(self.result_dir, exist_ok=True)
            config_dir = os.path.join(self.result_dir, 'config')
            os.makedirs(config_dir)

            # initialize problem and data storage (agent)
            try:
                problem, true_pfront = build_problem(config['problem'], get_pfront=True)
                self.agent_data = DataAgent(config, self.result_dir)
            except:
                tk.messagebox.showinfo('Error', 'Invalid values in configuration', parent=window)
                return

            self.config = config

            n_var, var_name, obj_name = problem.n_var, problem.var_name, problem.obj_name
            self.var_lb, self.var_ub = problem.xl, problem.xu
            if self.var_lb is None: self.var_lb = np.zeros(n_var)
            if self.var_ub is None: self.var_ub = np.ones(n_var)
            
            # update plot
            self.ax11.set_xlabel(obj_name[0])
            self.ax11.set_ylabel(obj_name[1])
            self.theta = radar_factory(n_var)
            self.fig1.delaxes(self.ax12)
            self.ax12 = self.fig1.add_subplot(self.gs1[1], projection='radar')
            self.ax12.set_xticks(self.theta)
            self.ax12.set_varlabels([f'{var_name[i]}\n[{self.var_lb[i]},{self.var_ub[i]}]' for i in range(n_var)])
            self.ax12.set_yticklabels([])
            self.ax12.set_title('Design Space', position=(0.5, 1.1))
            self.ax12.set_ylim(0, 1)

            self._init_draw(true_pfront)

            # disable changing saving location
            self.menu_file.entryconfig(0, state=tk.DISABLED)

            # change config create/change status
            self.menu_config.entryconfig(1, state=tk.DISABLED)
            self.menu_config.entryconfig(2, state=tk.NORMAL)

            # activate optimization button
            self.button_optimize.configure(state=tk.NORMAL)
            self.button_input.configure(state=tk.NORMAL)

            # refresh config display
            self.scrtext_config.configure(state=tk.NORMAL)
            self.scrtext_config.insert(tk.INSERT, yaml.dump(self.config, default_flow_style=False, sort_keys=False))
            self.scrtext_config.configure(state=tk.DISABLED)

            # trigger periodic refresh
            self.root.after(self.refresh_rate, self._refresh)

        else: # user changed config in the middle
            try:
                # some keys cannot be changed
                for key in ['n_init_sample']:
                    assert self.config_raw['general'][key] == config['general'][key]
                for key in ['name', 'n_var', 'n_obj', 'var_name', 'obj_name', 'ref_point']: # TODO
                    assert self.config_raw['problem'][key] == config['problem'][key]           
            except:
                tk.messagebox.showinfo('Error', 'Invalid configuration values for reloading', parent=window)
                return

            self.config = config

            # refresh config display
            self.scrtext_config.configure(state=tk.NORMAL)
            self.scrtext_config.delete('1.0', tk.END)
            self.scrtext_config.insert(tk.INSERT, yaml.dump(self.config, default_flow_style=False, sort_keys=False))
            self.scrtext_config.configure(state=tk.DISABLED)
        
        self._save_config(self.config)

    def _init_draw(self, true_pfront):
        '''
        First draw of performance space, hypervolume curve and model prediction error
        '''
        # load from database
        X, Y, hv_value, is_pareto = self.agent_data.load(['X', 'Y', 'hv', 'is_pareto'])

        # update status
        self.n_init_sample = len(Y)
        self.n_curr_sample = self.n_init_sample

        # plot performance space
        if true_pfront is not None:
            self.ax11.scatter(*true_pfront.T, color='gray', s=5, label='True Pareto front') # plot true pareto front
        self.scatter_x = X
        self.scatter_y = self.ax11.scatter(*Y.T, color='blue', s=10, label='Evaluated points')
        self.scatter_y_pareto = self.ax11.scatter(*Y[is_pareto].T, color='red', s=10, label='Approximated Pareto front')
        self.scatter_y_new = self.ax11.scatter([], [], color='m', s=10, label='New evaluated points')
        self.scatter_y_pred = self.ax11.scatter([], [], facecolors='none', edgecolors='m', s=15, label='New predicted points')
        self.ax11.legend(loc='upper right')
        self.line_y_pred_list = []

        # plot hypervolume curve
        self.line_hv = self.ax21.plot(list(range(self.n_init_sample)), hv_value)[0]
        self.ax21.set_title('Hypervolume: %.2f' % hv_value[-1])

        # plot prediction error curve
        self.line_error = self.ax22.plot([], [])[0]

         # mouse clicking event
        def check_design_values(event):
            if event.inaxes != self.ax11: return

            if event.button == MouseButton.LEFT and event.dblclick: # check certain design values
                # find nearest performance values with associated design values
                loc = [event.xdata, event.ydata]
                all_y = self.scatter_y._offsets
                closest_y, closest_idx = find_closest_point(loc, all_y, return_index=True)
                closest_x = self.scatter_x[closest_idx]
                x_str = '\n'.join([f'{name}: {val:.4g}' for name, val in zip(self.config['problem']['var_name'], closest_x)])

                # clear checked design values
                self._clear_design_space()

                # plot checked design values (TODO: fix annotation location)
                y_range = np.max(all_y, axis=0) - np.min(all_y, axis=0)
                text_loc = [closest_y[i] + 0.05 * y_range[i] for i in range(2)]
                self.annotate = self.ax11.annotate(x_str, xy=closest_y, xytext=text_loc,
                    bbox=dict(boxstyle="round", fc="w", alpha=0.7),
                    arrowprops=dict(arrowstyle="->"))
                transformed_x = (np.array(closest_x) - self.var_lb) / (self.var_ub - self.var_lb)
                self.line_x = self.ax12.plot(self.theta, transformed_x)[0]
                self.fill_x = self.ax12.fill(self.theta, transformed_x, alpha=0.2)[0]

            elif event.button == MouseButton.RIGHT: # clear checked design values
                self._clear_design_space()
                
            self.fig1.canvas.draw()
        
        self.fig1.canvas.mpl_connect('button_press_event', check_design_values)

        # refresh figure
        self.fig1.canvas.draw()
        self.fig2.canvas.draw()

    def _log(self, string):
        '''
        Log texts to ScrolledText widget for logging
        '''
        self.scrtext_log.configure(state=tk.NORMAL)
        self.scrtext_log.insert(tk.INSERT, string + '\n')
        self.scrtext_log.configure(state=tk.DISABLED)

    def _refresh(self):
        '''
        Refresh current GUI status and redraw if data has changed
        '''
        self._check_status()
        self._redraw()
        self.root.after(self.refresh_rate, self._refresh)

    def _start_worker(self, worker):
        '''
        Start a worker process
        '''
        worker.start()
        self.processes.append([self.process_id, worker])
        self._log(f'worker {self.process_id} started')
        self.process_id += 1

    def _check_status(self):
        '''
        Check if current processes are alive
        '''
        with self.lock:
            completed_ps = []
            for p in self.processes:
                pid, worker = p
                if not worker.is_alive():
                    completed_ps.append(p)
                    self._log(f'worker {pid} completed')
            for p in completed_ps:
                self.processes.remove(p)
        if len(self.processes) == 0:
            self.button_stop.configure(state=tk.DISABLED)
            if self.menu_config.entrycget(0, 'state') == tk.DISABLED:
                self.menu_config.entryconfig(0, state=tk.NORMAL)
            if self.menu_config.entrycget(2, 'state') == tk.DISABLED:
                self.menu_config.entryconfig(2, state=tk.NORMAL)

    def _clear_design_space(self):
        '''
        Clear design space value and annotation
        '''
        if self.annotate is not None:
            self.annotate.remove()
            self.annotate = None
        if self.line_x is not None:
            self.line_x.remove()
            self.line_x = None
        if self.fill_x is not None:
            self.fill_x.remove()
            self.fill_x = None

    def _redraw_performance_space(self, draw_iter=None):
        '''
        Redraw performance space
        '''
        X, Y, Y_expected, is_pareto, batch_id = self.agent_data.load(['X', 'Y', 'Y_expected', 'is_pareto', 'batch_id'])
        if draw_iter is not None and draw_iter < batch_id[-1]:
            draw_idx = batch_id <= draw_iter
            X, Y, Y_expected, batch_id = X[draw_idx], Y[draw_idx], Y_expected[draw_idx], batch_id[draw_idx]
            is_pareto = check_pareto(Y)
        
        # replot evaluated & pareto points
        self.scatter_x = X
        self.scatter_y.set_offsets(Y)
        self.scatter_y_pareto.set_offsets(Y[is_pareto])
        
        # rescale plot
        x_min, x_max = np.min(Y[:, 0]), np.max(Y[:, 0])
        y_min, y_max = np.min(Y[:, 1]), np.max(Y[:, 1])
        x_offset = (x_max - x_min) / 20
        y_offset = (y_max - y_min) / 20
        curr_x_min, curr_x_max = self.ax11.get_xlim()
        curr_y_min, curr_y_max = self.ax11.get_ylim()
        x_min, x_max = min(x_min - x_offset, curr_x_min), max(x_max + x_offset, curr_x_max)
        y_min, y_max = min(y_min - y_offset, curr_y_min), max(y_max + y_offset, curr_y_max)
        self.ax11.set_xlim(x_min, x_max)
        self.ax11.set_ylim(y_min, y_max)

        # replot new evaluated & predicted points
        if self.scatter_y_new is not None:
            self.scatter_y_new.remove()
            self.scatter_y_new = None
        if self.scatter_y_pred is not None:
            self.scatter_y_pred.remove()
            self.scatter_y_pred = None
        for line in self.line_y_pred_list:
            line.remove()
        self.line_y_pred_list = []

        if batch_id[-1] > 0:
            last_batch_idx = np.where(batch_id == batch_id[-1])[0]
            self.scatter_y_new = self.ax11.scatter(*Y[last_batch_idx].T, color='m', s=10, label='New evaluated points')
            self.scatter_y_pred = self.ax11.scatter(*Y_expected[last_batch_idx].T, facecolors='none', edgecolors='m', s=15, label='New predicted points')
            for y, y_expected in zip(Y[last_batch_idx], Y_expected[last_batch_idx]):
                line = self.ax11.plot([y[0], y_expected[0]], [y[1], y_expected[1]], '--', color='m', alpha=0.5)[0]
                self.line_y_pred_list.append(line)

        self.fig1.canvas.draw()

    def _redraw(self):
        '''
        Redraw performance space, hypervolume curve and model prediction error
        '''
        # check if needs redraw
        if self.agent_data.get_sample_num() == self.n_curr_sample: return

        # load from database
        hv_value, pred_error, batch_id = self.agent_data.load(['hv', 'pred_error', 'batch_id'])
        self.n_curr_sample = len(batch_id)

        # replot performance space if currently focusing on the lastest iteration
        if self.curr_iter.get() == self.max_iter:
            self.max_iter = batch_id[-1]
            self.scale_iter.configure(to=self.max_iter)
            self.curr_iter.set(self.max_iter)
            self._redraw_performance_space()
        else:
            self.max_iter = batch_id[-1]
            self.scale_iter.configure(to=self.max_iter)
            
        # replot hypervolume curve
        self.line_hv.set_data(list(range(self.n_curr_sample)), hv_value)
        self.ax21.relim()
        self.ax21.autoscale_view()
        self.ax21.set_title('Hypervolume: %.2f' % hv_value[-1])

        # replot prediction error curve
        self.line_error.set_data(list(range(self.n_init_sample, self.n_curr_sample)), pred_error[self.n_init_sample:])
        self.ax22.relim()
        self.ax22.autoscale_view()
        self.ax22.set_title('Model Prediction Error: %.2f%%' % pred_error[-1])

        # refresh figure
        self.fig2.canvas.draw()

    def mainloop(self):
        '''
        Start mainloop of GUI
        '''
        tk.mainloop()

    def _quit(self):
        '''
        Quit handling
        '''
        if self.agent_data is not None:
            self.agent_data.quit()

        for p in self.processes:
            _, worker = p
            worker.terminate()

        self.root.quit()
        self.root.destroy()