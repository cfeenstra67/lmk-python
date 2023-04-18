import { DOMWidgetModel, ISerializers } from "@jupyter-widgets/base";
import { createModelContext } from "../hooks/model";
import { MODULE_NAME, MODULE_VERSION } from "../version";

export interface NotificationChannel {
  notificationChannelId: string;
  name: string;
  order: number;
  isDefault: boolean;
  payload: any;
  createdAt: string;
  lastUpdatedAt: string;
}

export interface Notification {
  eventId: string;
  channels: {
    notificationChannelId: string;
    type: "email" | "text-message";
    name: string;
  }[];
}

export interface ILMKModel {
  state: "needs-auth" | "auth-in-progress" | "auth-error" | "authenticated";
  url: string;
  notebook_name: string;
  auth_url: string;
  jupyter_state: "idle" | "running";
  jupyter_execution_num: number;
  jupyter_cell_state: "none" | "running" | "error" | "success" | "cancelled";
  jupyter_cell_started_at: number;
  jupyter_cell_finished_at: number;
  jupyter_cell_error: string;
  monitoring_state: "none" | "error" | "stop";
  notify_min_execution: number;
  notify_min_time: number;
  channels_state: "none" | "loading" | "forbidden" | "loaded" | "error";
  selected_channel: string;
  channels: NotificationChannel[];
  sent_notifications: Notification[];
}

export const {
  Provider: WidgetViewProvider,
  useModel: useWidgetModel,
  useModelEvent: useWidgetModelEvent,
  useModelState: useWidgetModelState,
  useTransport: useWidgetTransport,
} = createModelContext<ILMKModel>();

export function useMonitoringState(): [
  ILMKModel["monitoring_state"],
  (state: ILMKModel["monitoring_state"]) => void
] {
  const [monitoringState, setMonitoringState] =
    useWidgetModelState("monitoring_state");
  const setNotifyMinExecution = useWidgetModelState("notify_min_execution")[1];
  const setNotifyMinTime = useWidgetModelState("notify_min_time")[1];
  const [jupyterExecutionNum] = useWidgetModelState("jupyter_execution_num");

  const setState = (state: ILMKModel["monitoring_state"]) => {
    setMonitoringState(state);
    setNotifyMinTime(Date.now());
    setNotifyMinExecution(jupyterExecutionNum);
  };

  return [monitoringState, setState];
}

const defaultModelProperties: ILMKModel = {
  state: "needs-auth",
  url: "",
  notebook_name: "",
  auth_url: "",
  jupyter_state: "idle",
  jupyter_execution_num: -1,
  jupyter_cell_state: "none",
  jupyter_cell_started_at: -1,
  jupyter_cell_finished_at: -1,
  jupyter_cell_error: "",
  monitoring_state: "none",
  notify_min_execution: -1,
  notify_min_time: -1,
  channels_state: "none",
  channels: [],
  selected_channel: "default",
  sent_notifications: [],
};

export class LMKModel extends DOMWidgetModel {
  defaults() {
    return {
      ...super.defaults(),
      _model_name: LMKModel.model_name,
      _model_module: LMKModel.model_module,
      _model_module_version: LMKModel.model_module_version,
      _view_name: LMKModel.view_name,
      _view_module: LMKModel.view_module,
      _view_module_version: LMKModel.view_module_version,
      ...defaultModelProperties,
    };
  }

  static serializers: ISerializers = {
    ...DOMWidgetModel.serializers,
    // Add any extra serializers here
  };

  static model_name = "LMKModel";
  static model_module = MODULE_NAME;
  static model_module_version = MODULE_VERSION;
  static view_name = "LMKView"; // Set to null if no view
  static view_module = MODULE_NAME; // Set to null if no view
  static view_module_version = MODULE_VERSION;
}
