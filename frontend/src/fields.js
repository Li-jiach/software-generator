import fieldDefinitions from '../../backend/src/main/resources/fields.json'

export const FIELDS = fieldDefinitions.filter(field => !field.legacy)
export const GROUPS = {basic:'申请与开发信息', environment:'开发与运行环境', features:'功能与技术特点'}
