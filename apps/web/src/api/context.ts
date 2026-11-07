import { createContext, useContext } from 'react'
import { api as defaultApi } from '.'
import type { Api } from './client'

/** The app's API client; tests provide one over the mock fetch. */
export const ApiContext = createContext<Api>(defaultApi)
export const useApi = () => useContext(ApiContext)
