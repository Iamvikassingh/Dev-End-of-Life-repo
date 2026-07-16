/**
 * AWS Amplify / Cognito configuration.
 * Reads values from environment variables set in .env.local.
 * If REACT_APP_COGNITO_USER_POOL_ID is not set, auth is disabled
 * and all API calls go out without an Authorization header.
 */
const amplifyConfig = {
  Auth: {
    Cognito: {
      userPoolId:     process.env.REACT_APP_COGNITO_USER_POOL_ID ?? "",
      userPoolClientId: process.env.REACT_APP_COGNITO_CLIENT_ID ?? "",
      region:         process.env.REACT_APP_COGNITO_REGION ?? "us-east-1",
      loginWith: {
        email: true,
      },
    },
  },
};

export default amplifyConfig;

/** True when Cognito env vars are provided. */
export const authEnabled =
  Boolean(process.env.REACT_APP_COGNITO_USER_POOL_ID) &&
  Boolean(process.env.REACT_APP_COGNITO_CLIENT_ID);
