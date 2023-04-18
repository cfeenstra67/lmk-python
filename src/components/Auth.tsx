import { useEffect } from 'react';
import {
  useWidgetModel,
  useWidgetModelState,
  useWidgetTransport,
} from '../lib/widget-model';
import Loader from './Loader';

export default function Auth() {
  const [authUrl] = useWidgetModelState('auth_url');
  const [widgetState] = useWidgetModelState('state');
  const model = useWidgetModel();
  const transport = useWidgetTransport();

  useEffect(() => {
    if (authUrl || !model || widgetState !== 'needs-auth') {
      return;
    }

    async function load() {
      await transport('initiate-auth', {});
    }

    load();
  }, [authUrl, model, transport, widgetState]);

  useEffect(() => {
    if (!authUrl || !model || widgetState !== 'auth-in-progress') {
      return;
    }
    window.open(authUrl, 'popup');
  }, [authUrl, model, transport, widgetState]);

  if (widgetState === 'authenticated') {
    return null;
  }

  return (
    <div className="lmk-flex lmk-items-center lmk-content-center lmk-h-full lmk-grow lmk-flex-col">
      {!authUrl ? (
        <div className="lmk-flex lmk-m-2 lmk-flex-col lmk-items-center lmk-gap-4">
          <Loader size={5} />
          <h2>Getting auth URL</h2>
        </div>
      ) : (
        <div className="lmk-flex lmk-m-2 lmk-flex-col lmk-items-center lmk-gap-4">
          <Loader size={5} />
          <div className="lmk-flex lmk-flex-col lmk-items-center">
            <h2 className="lmk-m-0">Waiting for authentication</h2>
            <p className="lmk-m-0">A new window should open for you to authenticate with LMK.</p>
            <p className="lmk-m-0">If one does not open, you can manually navigate to:</p>
            <p className="lmk-m-0">
              <a href={authUrl} target="_blank">
                {authUrl}
              </a>
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
