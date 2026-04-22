import Axios, { type AxiosRequestConfig } from 'axios'

const AXIOS_INSTANCE = Axios.create({ baseURL: '' })

export const customInstance = <T>(config: AxiosRequestConfig): Promise<T> => {
  const source = Axios.CancelToken.source()
  const promise = AXIOS_INSTANCE({
    ...config,
    cancelToken: source.token,
  }).then(({ data }) => data)

  // @ts-expect-error - cancel property for react-query
  promise.cancel = () => source.cancel('Query was cancelled')

  return promise
}
