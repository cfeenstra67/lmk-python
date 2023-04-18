import ms from 'ms';
import { useNow } from '../hooks/now';
import { useWidgetModelState, ILMKModel, useMonitoringState } from '../lib/widget-model';
import Navbar from './Navbar';

const stateNames: Record<ILMKModel['jupyter_state'], React.ReactNode> = {
  idle: <span className="lmk-text-warn">Idle</span>,
  running: <span className="lmk-text-success">Running</span>,
};

function Monitoring() {
  const [jupyterState] = useWidgetModelState('jupyter_state');
  const [jupyterExecutionNum] = useWidgetModelState('jupyter_execution_num');
  const [jupyterCellState] = useWidgetModelState('jupyter_cell_state');
  const [jupyterCellError] = useWidgetModelState('jupyter_cell_error');
  const [jupyterCellStartedAt] = useWidgetModelState('jupyter_cell_started_at');
  const [jupyterCellFinishedAt] = useWidgetModelState(
    'jupyter_cell_finished_at'
  );
  const [monitoringState, setMonitoringState] = useMonitoringState();

  const clickHandler = (event: ILMKModel['monitoring_state']) => () => {
    if (monitoringState === event) {
      setMonitoringState('none');
    } else {
      setMonitoringState(event);
    }
  };

  const now = useNow();

  return (
    <div className="lmk-grid lmk-grid-cols-1 lg:lmk-grid-cols-2 lg:lmk-grid-rows-1 lmk-gap-3 lmk-pt-2">
      <div className="lmk-flex lmk-flex-col lmk-gap-3 lmk-border-editorBorder lmk-border-solid lmk-rounded-xl lmk-box-border lmk-border lmk-p-4">
        <h3 className="lmk-text-lg">Notebook: {stateNames[jupyterState]}</h3>
        <div>
          {jupyterCellState === 'none' ? (
            <p>No cells have been run yet</p>
          ) : jupyterCellState === 'running' ? (
            <p>
              Cell{' '}
              <span className="jp-lmk-code lmk-text-warn">
                [{jupyterExecutionNum}]
              </span>
              &nbsp; has been running for {ms(now - jupyterCellStartedAt)}
            </p>
          ) : jupyterCellState === 'success' ? (
            <p>
              Cell{' '}
              <span className="jp-lmk-code lmk-text-success">
                [{jupyterExecutionNum}]
              </span>
              &nbsp; ran successfully {ms(Date.now() - jupyterCellFinishedAt)}{' '}
              ago.
            </p>
          ) : (
            <>
              <p>
                Cell{' '}
                <span className="jp-lmk-code lmk-text-error">
                  [{jupyterExecutionNum}]
                </span>
                &nbsp; exited with an error{' '}
                {ms(Date.now() - jupyterCellFinishedAt)} ago:&nbsp;
                <code>{jupyterCellError}</code>
              </p>
            </>
          )}
        </div>
      </div>
      <div className="lmk-grid lmk-grid-cols-[max-content_1fr] lmk-gap-3 lmk-border-editorBorder lmk-border-solid lmk-rounded-xl lmk-box-border lmk-border lmk-p-4">
        <h3 className="lmk-col-span-2 lmk-text-lg">
          Monitoring:{' '}
          {monitoringState === 'none' ? (
            <span className="lmk-text-warn">Disabled</span>
          ) : (
            <span className="lmk-text-success">Enabled</span>
          )}
        </h3>
        <input
          type="radio"
          id="lmk-monitoring-stop"
          checked={monitoringState === 'stop'}
          onClick={clickHandler('stop')}
        />
        <label htmlFor="lmk-monitoring-stop">
          Notify me when the current execution <b>stops</b>
        </label>
        <input
          type="radio"
          id="lmk-monitoring-error"
          checked={monitoringState === 'error'}
          onClick={clickHandler('error')}
        />
        <label htmlFor="lmk-monitoring-error">
          Notify me when if the current execution <b>fails</b>
        </label>
      </div>
    </div>
  );
}

export default function WidgetContent() {
  return (
    <div className="lmk-flex lmk-flex-col lmk-items-stretch lmk-gap-1 lmk-grow">
      <Navbar />
      <Monitoring />
    </div>
  );
}
